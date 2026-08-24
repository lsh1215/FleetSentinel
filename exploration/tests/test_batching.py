"""배치 계약 검증 — docs/sdd.md §3 S-3."""

from __future__ import annotations

import pytest

from fleetsentinel_ingest.batching import (
    DEFAULT_WINDOW_US,
    BatchStats,
    batch_by_window,
)

W = DEFAULT_WINDOW_US  # 100_000 us


def rec(t: int, channel: str = "ms_imu", eid: str | None = None) -> dict:
    return {"sensor_time": t, "channel": channel, "event_id": eid or f"E{t}"}


def test_records_land_in_absolute_aligned_windows() -> None:
    """창은 epoch 절대 시각에 정렬된다 — 첫 레코드 기준이 아니다."""
    batches = list(batch_by_window([rec(150_000), rec(199_999), rec(200_000)], "AV-0001"))
    assert [b.window_start for b in batches] == [100_000, 200_000]
    assert [b.count for b in batches] == [2, 1]


def test_window_end_is_exclusive_upper_bound() -> None:
    (batch,) = list(batch_by_window([rec(100_000)], "AV-0001"))
    assert batch.window_start == 100_000
    assert batch.window_end == 100_000 + W


def test_unordered_input_produces_ordered_batches() -> None:
    """입력 순서에 무관해야 한다 — 재전송·지연이 창 배정을 바꾸면 재현이 깨진다."""
    shuffled = [rec(250_000), rec(30_000), rec(180_000), rec(120_000)]
    batches = list(batch_by_window(shuffled, "AV-0001"))
    assert [b.window_start for b in batches] == [0, 100_000, 200_000]
    assert [r["sensor_time"] for r in batches[1].records] == [120_000, 180_000]


def test_batching_is_deterministic_regardless_of_arrival_order() -> None:
    """같은 레코드 집합은 순서가 어떻든 동일한 배치 구성을 낸다."""
    records = [rec(t) for t in (5_000, 99_999, 100_001, 250_000)]
    forward = [(b.window_start, [r["event_id"] for r in b.records]) for b in batch_by_window(records, "V")]
    backward = [(b.window_start, [r["event_id"] for r in b.records]) for b in batch_by_window(list(reversed(records)), "V")]
    assert forward == backward


def test_no_records_are_dropped() -> None:
    """무손실 — 부분 창도 버리지 않는다."""
    records = [rec(t) for t in range(0, 1_000_000, 7_331)]
    batched = [r for b in batch_by_window(records, "AV-0001") for r in b.records]
    assert len(batched) == len(records)
    assert {r["event_id"] for r in batched} == {r["event_id"] for r in records}


def test_event_id_survives_batching() -> None:
    """멱등성 단위는 레코드다 — 배치가 event_id를 가리거나 합치지 않는다."""
    records = [rec(10_000, eid="A"), rec(20_000, eid="B")]
    (batch,) = list(batch_by_window(records, "AV-0001"))
    assert [r["event_id"] for r in batch.records] == ["A", "B"]


def test_channels_are_mixed_within_a_window() -> None:
    """한 배치는 여러 CAN 채널을 함께 담는다 — 채널별 토픽이 아니다."""
    records = [rec(10_000, "ms_imu"), rec(20_000, "zoesensors"), rec(30_000, "pose")]
    (batch,) = list(batch_by_window(records, "AV-0001"))
    assert batch.channels == ["ms_imu", "pose", "zoesensors"]


@pytest.mark.parametrize("bad_window", [0, -1, -100_000])
def test_non_positive_window_is_rejected(bad_window: int) -> None:
    with pytest.raises(ValueError, match="양수"):
        list(batch_by_window([rec(0)], "AV-0001", window_us=bad_window))


def test_smaller_window_yields_more_batches() -> None:
    records = [rec(t) for t in range(0, 500_000, 10_000)]
    coarse = len(list(batch_by_window(records, "V", window_us=100_000)))
    fine = len(list(batch_by_window(records, "V", window_us=25_000)))
    assert fine > coarse


def test_stats_report_message_reduction() -> None:
    records = [rec(t) for t in range(0, 1_000_000, 1_000)]  # 1000건 / 1초
    stats = BatchStats()
    for b in batch_by_window(records, "AV-0001"):
        stats.observe(b)
    assert stats.n_records == 1000
    assert stats.n_batches == 10           # 1초 / 100ms
    assert stats.mean_records_per_batch == 100.0
    assert "1/100.0로 감소" in stats.summary()
