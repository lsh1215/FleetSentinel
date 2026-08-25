"""신호 레코드를 고정 시간창으로 묶는다. **⚠️ 이 설계는 폐기됐다 — 측정 하네스로만 남는다.**

## 왜 폐기됐는가

애플리케이션 수준 배치는 **축적 창만큼의 유실**을 만든다. 창에 모으는 동안 프로세스가
죽으면 그 안의 레코드는 전송 프로토콜에 들어간 적이 없어서 재전송 대상도 아니고, 결번도
남지 않는다 — **아무도 그것이 존재했다는 사실을 모른다.**

100ms 창을 채택했던 근거는 브로커 메시지 수를 줄이는 것이었는데, 그건
**전송 계층 배치**(Kafka 프로듀서 `linger.ms`, gRPC/HTTP2 프레임 병합)로 얻을 수 있다.
전송 계층 배치는 `send()` 이후에 일어나므로 프로토콜 보장 안쪽이다.

| | 애플리케이션 배치 | 전송 계층 배치 |
|---|---|---|
| 묶는 시점 | `send()` **이전** | `send()` **이후** |
| 크래시 시 | 창 안의 레코드가 조용히 사라진다 | 재전송 대상 |
| 메시지 수 절감 | 얻는다 | **똑같이 얻는다** |

즉 **대가를 치를 필요가 없는 거래였다.** 지금 설계는 레코드 단위 gRPC 스트림 +
온보드 WAL이다.

- 뒤집은 과정 — [설계 검토](../../docs/ingestion-design-review.md) §4.1
- 대체 설계 — [WAL 설계](../../docs/wal-design.md) · [ack·dedup 설계](../../docs/ack-dedup-design.md)

## 그런데 왜 남겨두는가

이 모듈의 창 정렬 로직이 **채널별 발생률 측정**에 쓰인다(`scripts/measure_batching.py`).
결정적 창 경계가 있어야 "이 채널이 초당 몇 레코드인가"를 재현 가능하게 셀 수 있다.
측정 도구로서는 유효하므로 테스트와 함께 남긴다.

**레코드 크기·발생률의 정본은 [데이터 설계](../../docs/data-design.md) §3이다.** 이
docstring에 있던 수치(1,466 rec/s · 180 B)는 초기 측정값이라 정본과 어긋난다.

## 아래 계약은 측정 하네스로서만 유효하다

- **창 경계는 `sensor_time` 기준**이다(`ingest_time`이 아니다). 같은 레코드는 항상 같은
  창에 들어간다 — 결정적(deterministic)이어야 측정이 재현된다.
- 창은 epoch 절대 시각에 정렬한다. `window_start = (sensor_time // window) * window`.
- **부분 창을 버리지 않는다.** 마지막 창이 덜 찼어도 그대로 방출한다.
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
