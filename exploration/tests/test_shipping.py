"""ack 프로토콜 검증.

가장 중요한 것은 마지막 두 테스트다 — **at-least-once 전송 + 멱등 dedup이 결과적
exactly-once가 되는지**를 SIGKILL로 실제 확인한다.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from fleetsentinel_ingest.dedup import SeqDedup
from fleetsentinel_ingest.shipping import (
    AckTracker,
    LoopbackGateway,
    WalShipper,
    read_gateway_log,
)
from fleetsentinel_ingest.wal import Wal

from ._ship_child import payload_for

CHILD = Path(__file__).parent / "_ship_child.py"
V = "n015-2018-07-24-11-22-45+0800"


# ── 누적 ack 계산 ───────────────────────────────────────────────────────


def test_cumulative_ack_advances_in_order():
    t = AckTracker(0)
    for i in range(10):
        t.complete(i)
        assert t.ack_seq == i


def test_ack_does_not_advance_past_a_hole():
    """구멍 위의 완료는 ack할 수 없다 — 그게 누적 ack의 의미다."""
    t = AckTracker(0)
    for s in [0, 1, 3, 4, 5]:
        t.complete(s)
    assert t.ack_seq == 1, "2가 안 끝났으므로 1까지만 안전하다"
    assert t.pending() == 3  # 3,4,5는 완료됐지만 ack 불가
    t.complete(2)
    assert t.ack_seq == 5  # 구멍이 메워지자 한 번에 전진
    assert t.pending() == 0


def test_out_of_order_completion_is_absorbed():
    """Kafka 콜백이 파티션 순서를 보장하지만 그에 의존하지 않는다."""
    t = AckTracker(100)
    for s in [105, 103, 101, 104, 100, 102]:
        t.complete(s)
    assert t.ack_seq == 105
    assert t.max_pending == 4


def test_duplicate_completion_is_harmless():
    t = AckTracker(0)
    t.complete(0)
    t.complete(0)
    assert t.ack_seq == 0


def test_ack_emitted_by_count():
    t = AckTracker(0, every_n=4, every_s=999.0)
    for i in range(3):
        t.complete(i)
        assert t.take() is None
    t.complete(3)
    assert t.take() == 3
    assert t.take() is None, "전진하지 않았으면 다시 방출하지 않는다"


def test_ack_emitted_by_time_when_count_is_short():
    """저부하에서도 커밋이 전진해야 한다 — 개수 조건만 두면 멈춘다."""
    t = AckTracker(0, every_n=1000, every_s=0.02)
    t.complete(0)
    assert t.take() is None
    time.sleep(0.03)
    assert t.take() == 0


# ── ack이 쓰기 성공에만 의존하는지 ──────────────────────────────────────


def test_ack_never_outruns_the_write(tmp_path):
    """쓰기가 실패한 구간은 ack되지 않고, 따라서 WAL에 남아 재전송된다.

    수신 직후 ack했다면 여기서 조용히 사라진다.
    """
    log = tmp_path / "gw.log"
    with Wal(tmp_path / "wal") as wal:
        holder = {}
        gw = LoopbackGateway(
            log_path=log,
            on_ack=lambda s: holder["s"].on_ack(s),
            every_n=1,
            every_s=0.0,
            fail_write_from=50,  # seq 50 이상은 Kafka 쓰기 실패
        )
        holder["s"] = shipper = WalShipper(wal, gw)
        for i in range(100):
            wal.append(payload_for(i))
        shipper.pump()

        assert gw.received == 100
        assert gw.written == 50
        assert wal.committed_seq == 49, "실패 구간을 ack하면 안 된다"
        # 50..99가 WAL에 남아 있다 → 재전송 가능
        remaining = [r.seq for r in wal.read_from(wal.committed_seq + 1)]
        assert remaining == list(range(50, 100))


def test_ack_regression_does_not_uncommit(tmp_path):
    with Wal(tmp_path / "wal") as wal:
        for i in range(100):
            wal.append(payload_for(i))
        shipper = WalShipper(wal, _NullTransport())
        shipper.on_ack(50)
        shipper.on_ack(20)  # 순서 뒤바뀐 ack
        assert wal.committed_seq == 50


def test_backpressure_stops_at_max_inflight(tmp_path):
    """ack이 안 오면 무한히 앞서 보내지 않는다."""
    with Wal(tmp_path / "wal") as wal:
        for i in range(1000):
            wal.append(payload_for(i))
        shipper = WalShipper(wal, _NullTransport(), max_inflight=64)
        assert shipper.pump() == 64
        assert shipper.pump() == 0, "ack 없이는 더 못 보낸다"
        shipper.on_ack(63)
        assert shipper.pump() == 64  # ack만큼 창이 열린다


class _NullTransport:
    def send(self, boot_id, seq, kind, payload):
        pass


# ── end-to-end: at-least-once + dedup = 결과적 exactly-once ─────────────


def _run_child(wal_dir, log, limit, every_n=512):
    return subprocess.run(
        [sys.executable, str(CHILD), str(wal_dir), str(log), str(limit), str(every_n)],
        capture_output=True,
        text=True,
        check=True,
    )


def _replay(log):
    """게이트웨이 로그를 dedup에 통과시켜 하류가 실제로 보는 것을 재현한다."""
    d = SeqDedup()
    accepted = []
    for boot_id, seq, _kind, payload in read_gateway_log(log):
        if d.accept(V, boot_id, seq):
            accepted.append((seq, payload))
    return d, accepted


def test_clean_run_delivers_exactly_once(tmp_path):
    log = tmp_path / "gw.log"
    _run_child(tmp_path / "wal", log, 2000)
    d, accepted = _replay(log)
    seqs = [s for s, _ in accepted]
    assert seqs == list(range(2000))
    assert all(p == payload_for(s) for s, p in accepted)
    assert d.stats().lost == 0
    assert d.stats().too_old == 0


def test_unacked_records_are_resent_after_restart(tmp_path):
    """ack을 못 받은 구간은 재시작 후 **다시** 간다. 결정론적으로 확인한다.

    이게 at-least-once의 정의다 — 그리고 dedup이 왜 필요한지의 이유다.
    """
    wal_dir, log = tmp_path / "wal", tmp_path / "gw.log"
    never_ack = {"every_n": 1 << 30, "every_s": 1e9}

    with Wal(wal_dir) as wal:
        gw = LoopbackGateway(log_path=log, on_ack=lambda s: None, **never_ack)
        shipper = WalShipper(wal, gw)
        for i in range(200):
            wal.append(payload_for(i))
        assert shipper.pump() == 200
        assert gw.written == 200
        assert wal.committed_seq == -1, "ack이 없으면 커밋이 전진하지 않는다"

    with Wal(wal_dir) as wal:  # 재시작
        gw2 = LoopbackGateway(log_path=log, on_ack=lambda s: None, **never_ack)
        shipper = WalShipper(wal, gw2)
        assert shipper.resume_from == 0, "커밋이 없으니 처음부터 다시 보낸다"
        assert shipper.pump() == 200

    raw = read_gateway_log(log)
    assert len(raw) == 400, "전량 재전송돼야 한다"
    d, accepted = _replay(log)
    assert [s for s, _ in accepted] == list(range(200)), "dedup이 정확히 한 번으로 만든다"
    assert d.stats().duplicate == 200


def test_sigkill_then_resume_is_exactly_once(tmp_path):
    """중단 없이 재개했을 때 하류가 보는 것은 **정확히 한 번, 결번 없이** 여야 한다.

    재전송량은 우연이 아니라 계산된다 — 죽는 순간의 커밋 지점과 게이트웨이 로그의 최고
    `seq` 차이가 곧 재전송량이다. 그 값을 예측해서 확인한다.
    """
    wal_dir, log = tmp_path / "wal", tmp_path / "gw.log"
    proc = subprocess.Popen(
        [sys.executable, str(CHILD), str(wal_dir), str(log), "400000", "512"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.6)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)

    raw_before = read_gateway_log(log)
    assert len(raw_before) > 1000, f"의미 있게 배송되기 전에 죽었다: {len(raw_before)}"
    max_logged = max(s for _, s, _, _ in raw_before)
    with Wal(wal_dir) as w:
        committed_at_kill = w.committed_seq
    # 게이트웨이에 들어갔지만 ack이 커밋으로 이어지지 않은 구간 = 재전송될 구간
    expected_dup = max_logged - committed_at_kill

    _run_child(wal_dir, log, 3000)

    raw = read_gateway_log(log)
    d, accepted = _replay(log)
    seqs = [s for s, _ in accepted]

    assert len(raw) - len(accepted) == expected_dup, "재전송량이 예측과 다르다"
    assert d.stats().duplicate == expected_dup
    assert seqs == list(range(len(seqs))), "결번이 있다 = 유실"
    assert all(p == payload_for(s) for s, p in accepted), "페이로드 정렬이 깨졌다"
    assert d.stats().lost == 0
    assert d.stats().too_old == 0
    assert d.progress(V).pending_holes == 0


def test_repeated_kills_still_exactly_once(tmp_path):
    """한 번의 크래시가 아니라 반복 크래시에서도 성립해야 한다."""
    wal_dir, log = tmp_path / "wal", tmp_path / "gw.log"
    for _ in range(3):
        proc = subprocess.Popen(
            [sys.executable, str(CHILD), str(wal_dir), str(log), "400000", "512"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.4)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)

    _run_child(wal_dir, log, 2000)
    d, accepted = _replay(log)
    seqs = [s for s, _ in accepted]
    assert seqs == list(range(len(seqs))), "결번이 있다 = 유실"
    assert all(p == payload_for(s) for s, p in accepted)
    assert d.stats().lost == 0
    assert d.stats().too_old == 0
