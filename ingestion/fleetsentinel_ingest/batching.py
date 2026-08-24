"""신호 레코드를 고정 시간창으로 묶어 Kafka 메시지 단위를 만든다.

## 왜 배치가 필요한가

차량 1대의 신호는 실측 **1,466 레코드/초**이고 레코드 하나가 약 180바이트다. 이대로
보내면 500대에서 **734,080 msg/s**이고, 페이로드보다 브로커 오버헤드가 커진다.

| | 메시지/초/대 | 메시지 크기 | 500대 |
|---|---|---|---|
| 원시 전송 | 1,466 | ~180 B | 734,080 msg/s |
| 100ms 배치 | 10 | ~27 KB | 5,000 msg/s |

## 계약

- **멱등성의 단위는 레코드다.** `event_id`는 레코드마다 유지되고, 배치는 전송 단위일 뿐
  중복 제거의 근거가 아니다. Flink는 배치를 펼친 뒤 `keyBy(event_id)`로 dedup한다.
- **창 경계는 `sensor_time` 기준**이다(`ingest_time`이 아니다). 재전송·지연이 있어도
  같은 레코드는 항상 같은 창에 들어간다 — 결정적(deterministic)이어야 재현이 된다.
- 창은 epoch 절대 시각에 정렬한다. `window_start = (sensor_time // window) * window`.
- **부분 창을 버리지 않는다.** 마지막 창이 덜 찼어도 그대로 방출한다(무손실).

배치의 대가는 **최대 `window_us` 만큼의 추가 지연**이다. 관제 요구(SDD R-3)에서
100ms는 무시 가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Sequence

DEFAULT_WINDOW_US = 100_000  # 100ms


@dataclass(frozen=True, slots=True)
class SignalBatch:
    """한 창에 속한 신호 레코드 묶음 = Kafka 메시지 1건."""

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


@dataclass
class BatchStats:
    """배치 효율 측정치 — SDD §6.2의 '배치 효율' 지표 산출용."""

    n_batches: int = 0
    n_records: int = 0
    sizes: List[int] = field(default_factory=list)

    def observe(self, batch: SignalBatch) -> None:
        self.n_batches += 1
        self.n_records += batch.count
        self.sizes.append(batch.count)

    @property
    def mean_records_per_batch(self) -> float:
        return self.n_records / self.n_batches if self.n_batches else 0.0

    @property
    def compression_ratio(self) -> float:
        """원시 전송 대비 메시지 수가 몇 분의 1로 줄었는가."""
        return self.mean_records_per_batch

    def summary(self) -> str:
        if not self.n_batches:
            return "배치 없음"
        return (
            f"배치 {self.n_batches:,}건 · 레코드 {self.n_records:,}건 · "
            f"평균 {self.mean_records_per_batch:.1f} rec/batch "
            f"(최소 {min(self.sizes)}, 최대 {max(self.sizes)}) · "
            f"메시지 수 1/{self.compression_ratio:.1f}로 감소"
        )
