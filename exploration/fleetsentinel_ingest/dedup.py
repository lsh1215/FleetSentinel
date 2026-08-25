"""`seq` 기반 dedup — 상태가 데이터 양이 아니라 **차량 수**에 비례한다.

## 왜 `event_id` 집합이 아닌가

레코드마다 UUID를 달고 "이미 본 UUID 집합"으로 중복을 걸러내는 방식은 상태가
**초당 레코드 수 × TTL** 로 자란다. 실측 부하(차량당 1,295 rec/s)에서:

    TTL 30분, 500대  →  74.6 GB

`seq`가 차량별로 단조 증가하면 "이 차량에서 어디까지 봤는가"를 정수로 들고 있으면 된다.
상태가 **차량 수** 에 비례하고 데이터 양과 무관해진다:

    윈도우 4,096, 500대  →  260 KB      (287,000배 절감)

`seq`의 단조성은 WAL이 append 시점에 발급하므로 보장된다(`test_seq_is_monotonic_across_restart`).

## 왜 정수 하나로는 부족한가

`last_seen` 하나만 두고 `seq <= last_seen` 을 중복으로 판정하면, **순서 역전으로 늦게
도착한 새 레코드를 유실**한다. 순서 역전이 생기는 경로:

* Kafka 파티션 수가 바뀌면(repartition) 같은 `vehicle_id`가 다른 파티션으로 가고
  파티션 간 순서 보장이 없다
* 같은 차량이 스트림을 두 개 열면(재연결 중복, 로드밸런서 재시도) 두 게이트웨이가
  같은 파티션에 인터리빙해 쓴다

그래서 `last_seen` 하나가 아니라 **최근 W개 구간의 비트맵**을 둔다. TCP SACK과 같은
구조다. 윈도우 밖(`seq <= last_seen - W`)은 중복으로 취급하되 **따로 계수해서 드러낸다** —
진짜 새 레코드를 버렸을 수 있는 유일한 경로이므로 조용히 넘어가면 안 된다.

## 부수 효과 — 유실이 관측 가능해진다

비트맵이 있으면 "구멍 없이 연속으로 받은 최고 `seq`"(`contiguous`)를 계산할 수 있다.
`last_seen - contiguous` 가 줄지 않고 남아 있으면 그게 유실이다. 즉 **결번 = 유실** 판정을
재생기 테스트가 아니라 **운영 중 스트림에서** 할 수 있다([SDD](../../docs/sdd.md) L-12).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["SeqDedup", "DedupStats", "VehicleProgress", "DEFAULT_WINDOW"]

#: 기본 윈도우. 4,096 레코드 = 실측 1,295 rec/s에서 약 3.2초 분량.
#: 비트맵 512 B/차량 — 3.2초를 넘겨 도착한 레코드는 이미 다른 문제가 있다는 신호다.
DEFAULT_WINDOW = 4096


@dataclass(frozen=True, slots=True)
class VehicleProgress:
    """차량 하나의 수신 진행 상황."""

    vehicle_id: str
    boot_id: str
    #: 지금까지 본 가장 큰 `seq`
    last_seen: int
    #: **구멍 없이** 연속으로 받은 최고 `seq`. `last_seen`과의 차이가 미결 구멍이다
    contiguous: int
    #: 윈도우 밖으로 밀려나 회복 불가로 확정된 결번 수 = 유실
    lost: int
    #: 아직 안 온 레코드 수. 지각 도착으로 메워질 수도, 유실로 굳을 수도 있다.
    #: `last_seen - contiguous`(미결 구간의 폭)와는 다르다 — 그 구간에 이미
    #: 지각 도착한 레코드가 섞여 있고 `last_seen` 자신은 항상 도착한 상태다
    pending_holes: int


@dataclass(slots=True)
class DedupStats:
    accepted: int = 0
    #: 비트맵에서 이미 봤다고 확인된 것 — 정상적인 재전송
    duplicate: int = 0
    #: 윈도우 밖이라 중복으로 취급한 것. **0이 아니면 조사해야 한다**
    too_old: int = 0
    #: 순서 역전으로 늦게 도착했으나 살려낸 것 — 정수 하나로는 버렸을 레코드
    late: int = 0
    #: `boot_id`가 바뀌어 상태를 리셋한 횟수 = WAL이 사라진 차량
    boot_resets: int = 0
    #: 회복 불가로 확정된 결번 총계
    lost: int = 0
    vehicles: int = 0
    #: 비트맵 + 커서가 차지하는 바이트(설계상 크기, Python 객체 오버헤드 제외)
    state_bytes: int = 0


@dataclass(slots=True)
class _State:
    boot_id: str
    last_seen: int
    contiguous: int
    lost: int = 0
    bits: bytearray = field(default_factory=bytearray)


class SeqDedup:
    """`(vehicle_id, boot_id, seq)` 로 중복을 걸러낸다.

    비트맵은 `seq % window` 로 인덱싱하는 **환형 버퍼**다. 윈도우가 전진할 때 비트를
    옮기지 않고, 새로 들어오는 슬롯만 비운다.

    :param window: 순서 역전을 허용하는 폭. 2의 거듭제곱이어야 한다
    """

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        if window <= 0 or window & (window - 1):
            raise ValueError(f"window는 2의 거듭제곱이어야 한다: {window}")
        self.window = window
        self._mask = window - 1
        self._nbytes = window // 8
        self._v: dict[str, _State] = {}
        self._stats = DedupStats()

    # ── 판정 ────────────────────────────────────────────────────────────

    def accept(self, vehicle_id: str, boot_id: str, seq: int) -> bool:
        """이 레코드를 하류로 넘겨야 하면 True.

        중복이면 False. **판정은 멱등하다** — 같은 인자로 다시 부르면 False다.
        """
        st = self._v.get(vehicle_id)

        if st is None:
            # 첫 레코드. 이 아래는 확인할 방법이 없으므로 정상이라고 가정한다 —
            # Flink 상태가 체크포인트에서 복구되지 않은 경우에만 해당하고,
            # 그건 이 계층의 문제가 아니다.
            st = _State(boot_id, seq - 1, seq - 1, bits=bytearray(self._nbytes))
            self._v[vehicle_id] = st
        elif st.boot_id != boot_id:
            # WAL이 사라졌다 → `seq`가 0부터 다시 시작한다. 리셋하지 않으면 전량 유실.
            self._stats.boot_resets += 1
            st.boot_id = boot_id
            st.last_seen = st.contiguous = seq - 1
            st.lost = 0
            st.bits = bytearray(self._nbytes)

        if seq > st.last_seen:
            self._advance(st, seq)
            self._stats.accepted += 1
            return True

        if seq <= st.last_seen - self.window:
            # 윈도우 밖. 진짜 새 레코드였을 수 있다 — 계수해서 드러낸다.
            self._stats.too_old += 1
            return False

        if self._test(st, seq):
            self._stats.duplicate += 1
            return False

        # 순서 역전으로 늦게 도착한 새 레코드. `last_seen` 하나만 뒀다면 버렸을 것.
        self._set(st, seq)
        self._pull_contiguous(st)
        self._stats.late += 1
        self._stats.accepted += 1
        return True

    # ── 윈도우 전진 ─────────────────────────────────────────────────────

    def _advance(self, st: _State, seq: int) -> None:
        """`last_seen`을 `seq`까지 밀면서 밀려나가는 구멍을 유실로 확정한다.

        슬롯 `n % W`는 전진 전에 `n - W`를 담고 있다. 그래서 **비우기 전에 읽어야**
        그 `seq`가 도착했는지 알 수 있다. 이게 유실 계수의 근거다.
        """
        prev = st.last_seen
        end = min(seq, prev + self.window)

        for n in range(prev + 1, end + 1):
            old = n - self.window
            if old > st.contiguous:
                if not self._test(st, old):  # old와 n은 같은 슬롯이다
                    st.lost += 1
                    self._stats.lost += 1
                st.contiguous = old
            self._clear(st, n)

        if seq > end:
            # 점프가 윈도우보다 크다 — 전체 슬롯이 이미 무효화됐다.
            st.bits = bytearray(self._nbytes)
            floor = seq - self.window
            if floor > st.contiguous:
                # 이 구간은 도착한 적이 없다(미래였으므로). 전부 유실.
                gap = floor - st.contiguous
                st.lost += gap
                self._stats.lost += gap
                st.contiguous = floor

        st.last_seen = seq
        self._set(st, seq)
        self._pull_contiguous(st)

    def _pull_contiguous(self, st: _State) -> None:
        while st.contiguous < st.last_seen and self._test(st, st.contiguous + 1):
            st.contiguous += 1

    # ── 비트 연산 ───────────────────────────────────────────────────────

    def _slot(self, seq: int) -> tuple[int, int]:
        idx = seq & self._mask
        return idx >> 3, 1 << (idx & 7)

    def _test(self, st: _State, seq: int) -> bool:
        byte, bit = self._slot(seq)
        return bool(st.bits[byte] & bit)

    def _set(self, st: _State, seq: int) -> None:
        byte, bit = self._slot(seq)
        st.bits[byte] |= bit

    def _clear(self, st: _State, seq: int) -> None:
        byte, bit = self._slot(seq)
        st.bits[byte] &= ~bit & 0xFF

    # ── 관측 ────────────────────────────────────────────────────────────

    def progress(self, vehicle_id: str) -> VehicleProgress | None:
        """차량의 수신 진행 상황. **관측용이므로 핫 경로에서 부르지 않는다** —
        미결 구간을 정확히 세려면 비트를 훑어야 하고 그건 최대 `window` 회다."""
        st = self._v.get(vehicle_id)
        if st is None:
            return None
        arrived = sum(
            1 for n in range(st.contiguous + 1, st.last_seen + 1) if self._test(st, n)
        )
        return VehicleProgress(
            vehicle_id=vehicle_id,
            boot_id=st.boot_id,
            last_seen=st.last_seen,
            contiguous=st.contiguous,
            lost=st.lost,
            pending_holes=(st.last_seen - st.contiguous) - arrived,
        )

    def forget(self, vehicle_id: str) -> None:
        """차량 상태를 버린다. 차량이 은퇴했을 때만 부른다 — 살아있는 차량에 부르면
        다음 레코드가 첫 레코드로 취급돼 그 아래 구간을 검사할 수 없게 된다."""
        self._v.pop(vehicle_id, None)

    def stats(self) -> DedupStats:
        self._stats.vehicles = len(self._v)
        # 차량당 비트맵 + (boot_id, last_seen, contiguous, lost) 커서
        self._stats.state_bytes = len(self._v) * (self._nbytes + 8 * 3 + 16)
        return self._stats
