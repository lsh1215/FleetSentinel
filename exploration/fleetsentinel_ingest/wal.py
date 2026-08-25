"""온보드 WAL — 전송 전 durability를 위한 append-only 로컬 스풀.

설계 정본은 `docs/wal-design.md`. 이 구현은 **재생기용 단순화 버전**이며 그 설계의
핵심 성질을 실증하는 것이 목적이다:

  W-1 전송 전 durable      → 그룹 커밋 fsync
  W-2 재시작 시 재개       → 커밋 포인터
  W-3 디스크 유한          → 세그먼트 롤링 + 삭제
  W-6 손상 꼬리 복구       → 레코드별 CRC

## 레코드 포맷

    ┌────────┬─────────┬────────┬────────┬──────────────┐
    │ len:4  │ crc32:4 │ seq:8  │ kind:1 │ payload:len  │
    └────────┴─────────┴────────┴────────┴──────────────┘

`crc32`는 `seq + kind + payload`를 덮는다. 크래시 시점의 잘린 꼬리를 판별하는 유일한
수단이고, **CRC 실패를 오류가 아니라 "꼬리를 찾았다"로 해석**해 그 지점에서 잘라낸다.

`kind`로 경량 레코드와 `segment-ref`를 한 로그에 담는다(설계 §3.9 — WAL이 중량 경로의
outbox 역할을 겸한다).

## at-least-once면 충분하다

커밋 포인터가 뒤처져 있으면 재시작 후 이미 보낸 것을 다시 보낸다. 그건 중복이고 하류
`event_id` dedup이 흡수한다. WAL에서 exactly-once를 만들려 하면 복잡해지는데 이미 dedup
계층이 있으므로 그럴 필요가 없다 — 계층별 책임 분리.
"""

from __future__ import annotations

import os
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

HEADER = struct.Struct("<IIQB")  # len, crc32, seq, kind
HEADER_SIZE = HEADER.size  # 17

RecordKind = Literal[0, 1]
KIND_SIGNAL = 0
KIND_SEGMENT_REF = 1

SEGMENT_SUFFIX = ".seg"
COMMIT_FILE = "COMMIT"

# 기본값. 재생기용이라 설계 문서(64MB / 10ms)보다 작게 잡아 테스트가 빠르다.
DEFAULT_SEGMENT_BYTES = 4 * 1024 * 1024
DEFAULT_COMMIT_INTERVAL_S = 0.010
DEFAULT_COMMIT_BYTES = 4 * 1024


@dataclass(frozen=True, slots=True)
class WalRecord:
    seq: int
    kind: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class WalStats:
    """관측 지표. 적체량이 곧 "네트워크가 못 따라간다"의 신호다(설계 §3.7)."""

    appended: int
    committed_seq: int
    pending_records: int
    pending_bytes: int
    segments: int
    disk_bytes: int
    fsync_count: int
    dropped_seq_ranges: list[tuple[int, int]]


class Wal:
    """append-only 세그먼트 로그.

    :param root: 로그 디렉터리
    :param segment_bytes: 세그먼트 롤링 임계
    :param commit_interval_s: 그룹 커밋 주기. 전원 손실 시 최대 이 구간이 날아간다
    :param max_disk_bytes: 상한. 초과 시 **가장 오래된 세그먼트를 버린다**(설계 §3.6) —
        쓰기를 막으면 센서 계층으로 역전파돼 프로토콜 바깥에서 조용히 사라지는데,
        버리는 쪽은 `seq` 결번으로 탐지 가능하다
    """

    def __init__(
        self,
        root: Path,
        *,
        segment_bytes: int = DEFAULT_SEGMENT_BYTES,
        commit_interval_s: float = DEFAULT_COMMIT_INTERVAL_S,
        commit_bytes: int = DEFAULT_COMMIT_BYTES,
        max_disk_bytes: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.segment_bytes = segment_bytes
        self.commit_interval_s = commit_interval_s
        self.commit_bytes = commit_bytes
        self.max_disk_bytes = max_disk_bytes

        self._fh = None
        self._seg_start_seq = 0
        self._seg_bytes = 0
        self._unsynced = 0
        self._last_sync = time.monotonic()
        self._fsync_count = 0
        self._appended = 0
        self._dropped: list[tuple[int, int]] = []

        self._next_seq = self._recover()
        self._open_segment(self._next_seq)

    # ── 쓰기 ────────────────────────────────────────────────────────────

    def append(self, payload: bytes, kind: int = KIND_SIGNAL) -> int:
        """레코드를 추가하고 발급된 `seq`를 돌려준다.

        **센서 콜백을 막지 않는다** — 버퍼에 쓰고 조건이 되면 fsync한다. fsync를 매번 하면
        초당 1,295회가 되어 eMMC가 버티지 못한다(설계 §3.3).
        """
        seq = self._next_seq
        body = struct.pack("<QB", seq, kind) + payload
        crc = zlib.crc32(body) & 0xFFFFFFFF
        frame = HEADER.pack(len(payload), crc, seq, kind) + payload

        assert self._fh is not None
        self._fh.write(frame)
        self._seg_bytes += len(frame)
        self._unsynced += len(frame)
        self._next_seq = seq + 1
        self._appended += 1

        if self._seg_bytes >= self.segment_bytes:
            self._sync()
            self._fh.close()
            self._open_segment(self._next_seq)
        elif self._should_sync():
            self._sync()

        if self.max_disk_bytes is not None:
            self._enforce_disk_cap()
        return seq

    def _should_sync(self) -> bool:
        return (
            self._unsynced >= self.commit_bytes
            or (time.monotonic() - self._last_sync) >= self.commit_interval_s
        )

    def _sync(self) -> None:
        if self._fh is None or self._unsynced == 0:
            return
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._unsynced = 0
        self._last_sync = time.monotonic()
        self._fsync_count += 1

    def flush(self) -> None:
        """미동기화분을 강제로 durable하게 만든다. 정상 종료 경로에서 호출한다."""
        self._sync()

    # ── 읽기 ────────────────────────────────────────────────────────────

    def read_from(self, seq: int) -> Iterator[WalRecord]:
        """`seq` 이상인 레코드를 순서대로 돌려준다.

        손상된 꼬리를 만나면 **거기서 멈춘다**(예외를 던지지 않는다) — 크래시 시점의
        잘린 레코드는 정상적인 종료 조건이다.
        """
        for path in self._segments():
            for rec in _scan_segment(path):
                if rec.seq >= seq:
                    yield rec

    # ── 커밋 ────────────────────────────────────────────────────────────

    def commit(self, seq: int) -> None:
        """서버가 확인한 최고 `seq`를 반영하고 소비된 세그먼트를 회수한다.

        정밀할 필요가 없다 — 뒤처지면 재시작 후 재전송이 생기고, 그건 중복이며
        하류 dedup이 흡수한다.
        """
        tmp = self.root / (COMMIT_FILE + ".tmp")
        tmp.write_bytes(struct.pack("<Q", seq))
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        tmp.replace(self.root / COMMIT_FILE)  # 원자적 교체
        self._truncate_before(seq)

    @property
    def committed_seq(self) -> int:
        p = self.root / COMMIT_FILE
        if not p.exists():
            return -1
        raw = p.read_bytes()
        return struct.unpack("<Q", raw)[0] if len(raw) == 8 else -1

    # ── 복구 ────────────────────────────────────────────────────────────

    def _recover(self) -> int:
        """유효한 마지막 레코드를 찾아 다음 `seq`를 결정하고 손상 꼬리를 잘라낸다."""
        segments = self._segments()
        if not segments:
            return 0
        last = segments[-1]
        valid_end = 0
        last_seq = -1
        for rec, end in _scan_segment_with_offset(last):
            valid_end = end
            last_seq = rec.seq
        # 손상된 꼬리를 잘라낸다. 이게 W-6을 닫는다.
        if valid_end < last.stat().st_size:
            with open(last, "r+b") as f:
                f.truncate(valid_end)
                os.fsync(f.fileno())
        if last_seq >= 0:
            return last_seq + 1
        # 마지막 세그먼트가 통째로 손상이면 그 앞 세그먼트에서 이어받는다
        for path in reversed(segments[:-1]):
            seqs = [r.seq for r in _scan_segment(path)]
            if seqs:
                return seqs[-1] + 1
        return 0

    # ── 세그먼트 관리 ───────────────────────────────────────────────────

    def _open_segment(self, start_seq: int) -> None:
        self._seg_start_seq = start_seq
        self._seg_bytes = 0
        path = self.root / f"{start_seq:020d}{SEGMENT_SUFFIX}"
        self._fh = open(path, "ab")
        self._seg_bytes = path.stat().st_size

    def _segments(self) -> list[Path]:
        return sorted(self.root.glob(f"*{SEGMENT_SUFFIX}"))

    def _truncate_before(self, seq: int) -> None:
        """세그먼트를 **파일 통째로** 삭제해 회수한다(설계 §3.2).

        마지막 레코드의 `seq`가 커밋 지점 이하인 세그먼트만 지운다. 활성 세그먼트는
        건드리지 않는다.
        """
        segments = self._segments()
        for path in segments[:-1]:
            seqs = [r.seq for r in _scan_segment(path)]
            if seqs and seqs[-1] <= seq:
                path.unlink()

    def _enforce_disk_cap(self) -> None:
        assert self.max_disk_bytes is not None
        while self._disk_bytes() > self.max_disk_bytes:
            segments = self._segments()
            if len(segments) <= 1:
                return  # 활성 세그먼트는 못 버린다
            victim = segments[0]
            seqs = [r.seq for r in _scan_segment(victim)]
            if seqs:
                # 버린 구간을 기록해 나중에 대사할 수 있게 한다 — 탐지 가능한 유실.
                self._dropped.append((seqs[0], seqs[-1]))
            victim.unlink()

    def _disk_bytes(self) -> int:
        return sum(p.stat().st_size for p in self._segments())

    # ── 관측 ────────────────────────────────────────────────────────────

    def stats(self) -> WalStats:
        committed = self.committed_seq
        pending = [r for r in self.read_from(committed + 1)]
        return WalStats(
            appended=self._appended,
            committed_seq=committed,
            pending_records=len(pending),
            pending_bytes=sum(HEADER_SIZE + len(r.payload) for r in pending),
            segments=len(self._segments()),
            disk_bytes=self._disk_bytes(),
            fsync_count=self._fsync_count,
            dropped_seq_ranges=list(self._dropped),
        )

    def close(self) -> None:
        self._sync()
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "Wal":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ── 스캔 유틸 ───────────────────────────────────────────────────────────


def _scan_segment(path: Path) -> Iterator[WalRecord]:
    for rec, _ in _scan_segment_with_offset(path):
        yield rec


def _scan_segment_with_offset(path: Path) -> Iterator[tuple[WalRecord, int]]:
    """레코드와 **그 레코드가 끝나는 오프셋**을 함께 돌려준다.

    오프셋이 필요한 이유는 복구 시 손상 꼬리를 잘라낼 지점을 알아야 하기 때문이다.
    CRC 실패·길이 초과는 예외가 아니라 **종료 조건**으로 취급한다.
    """
    data = path.read_bytes()
    pos = 0
    n = len(data)
    while pos + HEADER_SIZE <= n:
        length, crc, seq, kind = HEADER.unpack_from(data, pos)
        end = pos + HEADER_SIZE + length
        if end > n:
            return  # 잘린 꼬리
        payload = data[pos + HEADER_SIZE : end]
        if zlib.crc32(struct.pack("<QB", seq, kind) + payload) & 0xFFFFFFFF != crc:
            return  # 손상된 꼬리
        yield WalRecord(seq=seq, kind=kind, payload=payload), end
        pos = end
