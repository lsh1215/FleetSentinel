"""dedup 계약 검증.

핵심은 두 가지다 — **중복은 반드시 걸러진다**, 그리고 **순서 역전은 유실이 아니다**.
후자가 `last_seen` 정수 하나로는 안 되는 이유이므로 가장 중요한 테스트다.
"""

import random

import pytest

from fleetsentinel_ingest.dedup import DEFAULT_WINDOW, SeqDedup

V = "n015-2018-07-24-11-22-45+0800"
B = "boot-a"


def test_first_records_pass_in_order():
    d = SeqDedup()
    assert all(d.accept(V, B, i) for i in range(100))
    p = d.progress(V)
    assert (p.last_seen, p.contiguous, p.pending_holes, p.lost) == (99, 99, 0, 0)


def test_exact_resend_is_rejected():
    d = SeqDedup()
    for i in range(100):
        d.accept(V, B, i)
    # ack이 유실돼 커밋이 안 됐다 → 클라이언트가 committed+1부터 재전송한다
    assert not any(d.accept(V, B, i) for i in range(50, 100))
    assert d.stats().duplicate == 50
    assert d.stats().accepted == 100  # 늘지 않았다


def test_judgement_is_idempotent():
    d = SeqDedup()
    assert d.accept(V, B, 0) is True
    assert d.accept(V, B, 0) is False
    assert d.accept(V, B, 0) is False


def test_out_of_order_arrival_is_not_a_loss():
    """`last_seen` 정수 하나만 뒀다면 여기서 41개를 잃는다."""
    d = SeqDedup()
    d.accept(V, B, 0)
    assert d.accept(V, B, 100) is True  # 크게 앞선 레코드가 먼저 도착
    p = d.progress(V)
    assert p.last_seen == 100
    assert p.contiguous == 0  # 1..99가 아직 구멍
    assert p.pending_holes == 99

    for i in range(1, 100):  # 뒤늦게 도착
        assert d.accept(V, B, i) is True, f"seq={i}를 유실했다"

    p = d.progress(V)
    assert (p.contiguous, p.pending_holes, p.lost) == (100, 0, 0)
    assert d.stats().late == 99
    assert d.stats().lost == 0


def test_shuffled_delivery_loses_nothing():
    """파티션 재배치·스트림 중복이 만드는 순서 뒤섞임 전체를 견딘다."""
    rng = random.Random(1215)
    order = list(range(2000))
    rng.shuffle(order)
    d = SeqDedup()
    assert sum(d.accept(V, B, s) for s in order) == 2000
    p = d.progress(V)
    assert (p.contiguous, p.lost) == (1999, 0)
    # 같은 순서로 한 번 더 → 전부 중복
    assert sum(d.accept(V, B, s) for s in order) == 0


def test_beyond_window_is_dropped_and_counted():
    """윈도우를 넘어서 지각한 레코드는 버린다 — 조용히 넘어가지 않고 계수한다."""
    d = SeqDedup(window=64)
    d.accept(V, B, 0)
    d.accept(V, B, 1000)  # 윈도우가 (936, 1000]으로 점프
    assert d.accept(V, B, 5) is False
    assert d.stats().too_old == 1
    assert d.stats().duplicate == 0  # 중복과 구별해서 센다


def test_window_must_be_power_of_two():
    with pytest.raises(ValueError, match="2의 거듭제곱"):
        SeqDedup(window=1000)


# ── 유실 탐지 — L-12를 닫는 부분 ─────────────────────────────────────────


def test_hole_pushed_out_of_window_is_declared_lost():
    """구멍이 윈도우 밖으로 밀려나면 회복 불가로 확정한다."""
    d = SeqDedup(window=64)
    for i in range(10):
        d.accept(V, B, i)
    # seq=10 하나를 빼먹는다 (WAL 디스크 상한으로 버려진 경우)
    for i in range(11, 200):
        d.accept(V, B, i)
    p = d.progress(V)
    assert p.lost == 1, "결번 1개를 유실로 확정해야 한다"
    assert p.contiguous == 199
    assert p.pending_holes == 0  # 확정됐으므로 미결이 아니다
    assert d.stats().lost == 1


def test_large_jump_counts_every_skipped_seq_as_lost():
    """윈도우보다 큰 점프 — 건너뛴 구간 전체가 유실이다."""
    d = SeqDedup(window=64)
    d.accept(V, B, 0)
    d.accept(V, B, 500)
    p = d.progress(V)
    # 1..436이 윈도우 밖으로 밀려났다. 437..499는 아직 미결 구멍
    assert p.lost == 500 - 64
    assert p.contiguous == 500 - 64
    assert p.pending_holes == 63


def test_loss_is_zero_on_a_healthy_stream():
    """정상 스트림에서 유실 지표가 0이어야 한다 — 아니면 지표를 못 믿는다."""
    d = SeqDedup(window=DEFAULT_WINDOW)
    for i in range(50_000):
        d.accept(V, B, i)
    assert d.stats().lost == 0
    assert d.stats().too_old == 0
    assert d.progress(V).pending_holes == 0


# ── boot_id — WAL이 사라진 차량 ──────────────────────────────────────────


def test_boot_change_resets_state():
    """WAL을 지우면 `seq`가 0부터 다시 시작한다. 리셋 없으면 전량 유실이다."""
    d = SeqDedup()
    for i in range(1000):
        d.accept(V, "boot-a", i)

    # 같은 boot_id로 낮은 seq → 중복
    assert d.accept(V, "boot-a", 5) is False
    # 새 boot_id로 같은 낮은 seq → 새 레코드다
    assert d.accept(V, "boot-b", 5) is True
    assert d.stats().boot_resets == 1

    p = d.progress(V)
    assert (p.boot_id, p.last_seen) == ("boot-b", 5)
    assert p.lost == 0  # 이전 생애의 계수를 끌고 오지 않는다


def test_boot_reset_does_not_inflate_loss():
    d = SeqDedup(window=64)
    d.accept(V, "boot-a", 0)
    d.accept(V, "boot-a", 5000)  # 유실 대량 발생
    assert d.progress(V).lost > 0
    d.accept(V, "boot-b", 0)
    assert d.progress(V).lost == 0


# ── 상태 크기 — 이 설계의 존재 이유 ──────────────────────────────────────


def test_state_is_proportional_to_vehicles_not_data():
    """`event_id` 집합이면 데이터 양에 비례해 자란다. 여기선 자라지 않아야 한다."""
    d = SeqDedup()
    for v in range(10):
        for i in range(20_000):  # 차량당 2만 레코드
            d.accept(f"veh-{v}", B, i)
    s = d.stats()
    assert s.accepted == 200_000
    assert s.vehicles == 10
    per_vehicle = s.state_bytes / s.vehicles
    assert per_vehicle < 600, f"차량당 {per_vehicle} B — 예상 520 B"

    # 데이터를 10배 더 넣어도 상태가 같다
    before = s.state_bytes
    for v in range(10):
        for i in range(20_000, 40_000):
            d.accept(f"veh-{v}", B, i)
    assert d.stats().state_bytes == before


def test_forget_releases_state():
    d = SeqDedup()
    d.accept(V, B, 0)
    assert d.stats().vehicles == 1
    d.forget(V)
    assert d.stats().vehicles == 0
