#!/usr/bin/env python3
"""배치 정책 실측 — 창 크기별 메시지 수·크기·지연 트레이드오프를 측정한다.

SDD §3 S-3(100ms 창 배치)의 근거 수치를 산출한다. 창 크기를 바꿔가며
차량당 메시지/초, 메시지 크기, 500대 환산치를 뽑는다.

사용:
    PYTHONPATH=. .venv/bin/python scripts/measure_batching.py --dataroot ../data/nuscenes
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nuscenes.nuscenes import NuScenes  # noqa: E402

from fleetsentinel_ingest.batching import BatchStats, batch_by_window  # noqa: E402
from fleetsentinel_ingest.nuscenes_source import extract_native_signals  # noqa: E402

FLEET = 500


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataroot", type=Path, required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--scenes", type=int, default=3)
    args = ap.parse_args()

    nusc = NuScenes(version=args.version, dataroot=str(args.dataroot), verbose=False)
    try:
        from nuscenes.can_bus.can_bus_api import NuScenesCanBus

        can = NuScenesCanBus(dataroot=str(args.dataroot))
    except Exception:
        can = None
        print("⚠️  CAN 확장 없음 — ego_pose만 측정된다")

    records, duration = [], 0.0
    for scene in nusc.scene[: args.scenes]:
        sigs = extract_native_signals(nusc, scene, vehicle_id="AV-0001", can_api=can)
        if not sigs:
            continue
        records += [dataclasses.asdict(s) for s in sigs]
        duration += (sigs[-1].sensor_time - sigs[0].sensor_time) / 1e6

    by_channel = collections.Counter(r["channel"] for r in records)
    print(f"측정: {args.scenes}장면 · {duration:.1f}초 · 신호 {len(records):,}건")
    print(f"차량 1대 신호 발생률: {len(records)/duration:,.1f} rec/s\n")
    print(f"  {'채널':<22} {'건수':>9} {'Hz':>8}")
    for ch, cnt in by_channel.most_common():
        print(f"  {ch:<22} {cnt:>9,} {cnt/duration:>7.1f}")

    print()
    print("=" * 92)
    print("창 크기별 트레이드오프")
    print("=" * 92)
    print(
        f"  {'창':>8} {'msg/s/대':>10} {'평균 rec/msg':>13} {'평균 크기':>11} "
        f"{'500대 msg/s':>13} {'추가 지연':>10}"
    )
    for window_ms in (0, 10, 50, 100, 250, 500, 1000):
        if window_ms == 0:
            per_s = len(records) / duration
            size = sum(len(json.dumps(r).encode()) for r in records[:500]) / min(500, len(records))
            print(
                f"  {'없음':>8} {per_s:>10,.1f} {1.0:>13.1f} {size:>8.0f} B "
                f"{per_s*FLEET:>13,.0f} {'0 ms':>10}"
            )
            continue
        stats = BatchStats()
        sizes = []
        for batch in batch_by_window(records, "AV-0001", window_us=window_ms * 1000):
            stats.observe(batch)
            if len(sizes) < 200:
                sizes.append(len(json.dumps(list(batch.records)).encode()))
        per_s = stats.n_batches / duration
        avg = sum(sizes) / len(sizes)
        print(
            f"  {window_ms:>6} ms {per_s:>10,.1f} {stats.mean_records_per_batch:>13.1f} "
            f"{avg/1024:>8.1f} KB {per_s*FLEET:>13,.0f} {f'≤{window_ms} ms':>10}"
        )

    print()
    print("  ▸ 창을 키우면 메시지 수가 선형으로 줄고 지연이 선형으로 는다.")
    print("  ▸ 100ms가 균형점 — 관제 요구(SDD R-3)에서 100ms는 무시 가능하고,")
    print("    500대에서 Kafka가 편하게 받는 규모로 떨어진다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
