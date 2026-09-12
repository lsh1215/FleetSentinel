"""대시보드 fixture용 신호 레코드를 고정 시간창으로 묶는다.

`scripts/export_fixture.py`에서 목업 SSE 재생 데이터를 만들 때 사용한다.
수집 경로의 레코드 단위 전송에는 사용하지 않는다.
창은 sensor_time의 절대 시각에 정렬하며 마지막 부분 창도 보존한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Sequence

DEFAULT_WINDOW_US = 100_000  # 100ms


@dataclass(frozen=True, slots=True)
class SignalBatch:
    """목업 SSE 재생에 사용할 한 시간창의 신호 레코드."""

    vehicle_id: str
    window_start: int          # epoch us, window_us 배수로 정렬됨
    window_end: int            # window_start + window_us (배타적 상한)
    records: Sequence[dict]

    @property
    def count(self) -> int:
        return len(self.records)

    @property
    def channels(self) -> List[str]:
        return sorted({r["channel"] for r in self.records if "channel" in r})


def batch_by_window(
    records: Iterable[dict],
    vehicle_id: str,
    window_us: int = DEFAULT_WINDOW_US,
    time_key: str = "sensor_time",
) -> Iterator[SignalBatch]:
    """레코드를 `window_us` 창으로 묶어 순서대로 방출한다.

    입력이 시간순이 아니어도 된다 — 창 배정은 절대 시각 기준이라 순서에 무관하고,
    방출만 창 시작 시각 순으로 정렬한다. 창 안 레코드도 `time_key`로 정렬해 담는다.

    :raises ValueError: `window_us`가 양수가 아닐 때
    """
    if window_us <= 0:
        raise ValueError(f"window_us는 양수여야 한다: {window_us}")

    buckets: Dict[int, List[dict]] = {}
    for record in records:
        start = (record[time_key] // window_us) * window_us
        buckets.setdefault(start, []).append(record)

    for start in sorted(buckets):
        rows = sorted(buckets[start], key=lambda r: r[time_key])
        yield SignalBatch(
            vehicle_id=vehicle_id,
            window_start=start,
            window_end=start + window_us,
            records=rows,
        )
