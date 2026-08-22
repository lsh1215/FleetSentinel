#!/usr/bin/env python3
"""nuScenes 장면 → MCAP 변환 CLI (P1).

사용:
    PYTHONPATH=. .venv/bin/python scripts/convert_scenes.py \
        --dataroot ../data/nuscenes --out ../data/mcap --scenes 2

장면을 N대 가상 차량에 배분한다(§6.2) — nuScenes는 20초 클립 모음이라 그대로
재생하면 끊기므로, 여러 장면을 동시 재생해 fleet 관제 화면을 만드는 구조다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nuscenes.nuscenes import NuScenes  # noqa: E402

from fleetsentinel_ingest.mcap_writer import write_scene_mcap  # noqa: E402
from fleetsentinel_ingest.nuscenes_source import extract_scene  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="nuScenes → MCAP 변환")
    ap.add_argument("--dataroot", type=Path, required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scenes", type=int, default=0, help="변환할 장면 수 (0=전체)")
    ap.add_argument("--vehicles", type=int, default=4, help="배분할 가상 차량 수")
    ap.add_argument("--no-raw", action="store_true", help="원시 센서 제외(경량만)")
    args = ap.parse_args()

    nusc = NuScenes(version=args.version, dataroot=str(args.dataroot), verbose=False)
    try:
        from nuscenes.can_bus.can_bus_api import NuScenesCanBus

        can = NuScenesCanBus(dataroot=str(args.dataroot))
        print(f"CAN bus 확장: 사용 가능")
    except Exception as exc:
        can = None
        print(f"CAN bus 확장: 없음 ({type(exc).__name__}) — 신호는 ego_pose만으로 축소")

    scenes = nusc.scene if args.scenes == 0 else nusc.scene[: args.scenes]
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []

    for i, scene in enumerate(scenes):
        vehicle_id = f"AV-{(i % args.vehicles) + 1:04d}"
        extract = extract_scene(nusc, scene, vehicle_id=vehicle_id, can_api=can)
        out_path = args.out / f"{scene['name']}.mcap"
        meta = write_scene_mcap(
            extract, dataroot=args.dataroot, out_path=out_path, include_raw=not args.no_raw
        )
        manifest.append(meta)
        mb = meta["size_bytes"] / 1e6
        print(
            f"  [{i+1}/{len(scenes)}] {scene['name']} → {out_path.name}  "
            f"{mb:7.1f}MB  veh={vehicle_id}  "
            f"신호 {meta['n_signals']:>3} · 인지 {meta['n_perception']:>4} · 원시 {meta['n_raw']:>4}"
        )

    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    total = sum(m["size_bytes"] for m in manifest)
    print(f"\n총 {len(manifest)}개 장면, {total/1e6:.1f}MB → {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
