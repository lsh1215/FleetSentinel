"""ack이 다른 스레드에서 올 때 WAL이 버티는가.

`LoopbackGateway`는 `send()` 안에서 동기로 ack을 돌려줬다. 그래서 커밋과 읽기가 항상
같은 스레드였고 경합이 없었다. :class:`~fleetsentinel_ingest.grpc_transport.GrpcTransport`
는 CACK을 **역방향 스트림에서 읽는 별도 스레드**로 받으므로 전제가 바뀐다:

    cack-reader 스레드 :  on_ack → Wal.commit → _truncate_before → path.unlink()
    배송기 스레드      :  pump   → WalCursor.read → _drain → exists() → open()

락이 없으면 `exists()`와 `open()` 사이에 파일이 사라져 `FileNotFoundError`가 난다.
"""

from __future__ import annotations

import threading

import pytest

from fleetsentinel_ingest.shipping import WalShipper
from fleetsentinel_ingest.wal import Wal


class _NullTransport:
    """전송은 이 테스트의 관심사가 아니다. 세그먼트 회수와 읽기의 경합만 본다."""

    def send(self, boot_id: str, seq: int, kind: int, payload: bytes) -> None:
        pass


def _fill(wal: Wal, n: int, payload_size: int = 256) -> None:
    blob = b"x" * payload_size
    for _ in range(n):
        wal.append(blob)


class TestConcurrentCommitAndRead:
    """세그먼트 삭제와 세그먼트 읽기가 겹치지 않아야 한다.

    **왜 상호배제를 직접 계측하는가** — 자연스러운 부하로는 이 경합이 재현되지 않는다.
    TOCTOU 창(`exists()` 직후 `open()` 직전)이 수 마이크로초이고 GIL이 그 사이 전환을
    거의 안 만든다. 실제로 락을 빼고 돌려도 4,000건 전송이 그냥 통과한다 — 즉 "예외가
    안 났다"는 것은 **아무것도 증명하지 못한다.**

    그래서 읽기 구간에 의도적으로 양보 지점을 넣어 창을 벌리고, 그 사이에 삭제가
    들어오는지를 본다. 락이 있으면 커밋 스레드가 막혀 겹칠 수 없고, 없으면 겹친다.
    """

    def test_truncate_never_overlaps_a_read(self, tmp_path, monkeypatch):
        import time as _time

        from fleetsentinel_ingest import wal as wal_mod

        wal = Wal(tmp_path, segment_bytes=8 * 1024)
        total = 2000
        _fill(wal, total)

        reading = threading.Event()
        overlaps: list[str] = []

        original_drain = wal_mod.WalCursor._drain
        original_truncate = Wal._truncate_before

        def instrumented_drain(self, limit, out):
            reading.set()
            _time.sleep(0.002)  # 창을 벌린다 — 락이 없으면 여기서 삭제가 끼어든다
            try:
                return original_drain(self, limit, out)
            finally:
                reading.clear()

        def instrumented_truncate(self, seq):
            if reading.is_set():
                overlaps.append(f"seq={seq} 읽는 중에 세그먼트를 지웠다")
            return original_truncate(self, seq)

        monkeypatch.setattr(wal_mod.WalCursor, "_drain", instrumented_drain)
        monkeypatch.setattr(Wal, "_truncate_before", instrumented_truncate)

        shipper = WalShipper(wal, _NullTransport(), max_inflight=total + 1)
        errors: list[BaseException] = []
        stop = threading.Event()

        def committer() -> None:
            try:
                while not stop.is_set():
                    sent = shipper.stats.sent
                    if sent > 0:
                        wal.commit(sent - 1)
                    _time.sleep(0.001)
            except BaseException as e:  # noqa: BLE001 — 스레드 밖으로 전파하려면 모아야 한다
                errors.append(e)

        t = threading.Thread(target=committer, name="committer", daemon=True)
        t.start()
        try:
            while shipper.stats.sent < total:
                if shipper.pump(budget=64) == 0 and shipper.stats.sent >= total:
                    break
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        finally:
            stop.set()
            t.join(timeout=10)

        assert not errors, f"경합에서 예외가 났다: {errors!r}"
        assert not overlaps, f"읽기와 세그먼트 삭제가 겹쳤다: {overlaps[:3]}"
        assert shipper.stats.sent == total

    def test_append_and_commit_interleave(self, tmp_path):
        """적재가 계속되는 중에 커밋이 들어와도 `seq`가 어긋나지 않는다."""
        wal = Wal(tmp_path, segment_bytes=8 * 1024)
        errors: list[BaseException] = []
        appended: list[int] = []
        stop = threading.Event()

        def committer() -> None:
            try:
                while not stop.is_set():
                    if appended:
                        wal.commit(max(0, appended[-1] - 100))
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        t = threading.Thread(target=committer, name="committer", daemon=True)
        t.start()
        try:
            for _ in range(3000):
                appended.append(wal.append(b"y" * 256))
        finally:
            stop.set()
            t.join(timeout=10)

        assert not errors, f"경합에서 예외가 났다: {errors!r}"
        # seq는 빈틈없이 단조 증가해야 한다 — 결번이 곧 유실이다.
        assert appended == list(range(len(appended)))


class TestLockDoesNotCoverTransport:
    """락을 전송 구간까지 넓히면 느린 게이트웨이가 WAL 전체를 멈춘다.

    `pump()`는 `cursor.read()`(락 안)와 `transport.send()`(락 밖)를 분리해야 한다.
    """

    def test_commit_proceeds_while_transport_blocks(self, tmp_path):
        wal = Wal(tmp_path, segment_bytes=8 * 1024)
        _fill(wal, 500)

        release = threading.Event()
        in_send = threading.Event()

        class _BlockingTransport:
            def send(self, boot_id, seq, kind, payload):
                in_send.set()
                # 첫 레코드에서 멈춰 선다 — 느린 게이트웨이를 흉내낸다.
                release.wait(timeout=10)

        shipper = WalShipper(wal, _BlockingTransport(), max_inflight=1000)
        pumper = threading.Thread(target=lambda: shipper.pump(budget=64), daemon=True)
        pumper.start()

        assert in_send.wait(timeout=10), "전송에 진입하지 못했다"

        # 전송이 막혀 있는 동안에도 커밋이 가능해야 한다.
        done = threading.Event()

        def commit_now() -> None:
            wal.commit(0)
            done.set()

        threading.Thread(target=commit_now, daemon=True).start()
        assert done.wait(timeout=5), "전송이 막힌 동안 커밋이 블록됐다 — 락이 너무 넓다"

        release.set()
        pumper.join(timeout=10)
