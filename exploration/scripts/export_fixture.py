#!/usr/bin/env python3
"""프론트엔드 개발용 픽스처 생성 — 실제 nuScenes 데이터에서 뽑는다.

백엔드(Spring Boot)가 아직 없으므로 프론트엔드는 목 서버로 개발한다. 다만 목 데이터를
지어내면 실제 레이트·형식과 어긋나 프론트 설계가 틀어진다. 그래서 **실제 MCAP/nuScenes에서
추출**하고, **설계상 전송 단위인 100ms 배치 형태**로 내보낸다.

산출물 (frontend/public/fixture/):
  meta.json      차량 목록, 지역, 시간 범위
  batches.json   100ms 배치 시퀀스 — SSE가 이걸 순서대로 흘린다
  clips.json     클립 카탈로그 (조건 태그 포함)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nuscenes.nuscenes import NuScenes  # noqa: E402

from fleetsentinel_ingest.batching import batch_by_window  # noqa: E402
from fleetsentinel_ingest.nuscenes_source import (  # noqa: E402
    extract_native_signals,
    extract_scene,
)

# scene.description 태그 규칙 — docs/data-design.md §7.2
# rain은 부정 후방탐색이 필요하다: "after rain"은 활성 강우가 아니다.
TAG_RULES = {
    "night": r"\bnight\b",
    "rain": r"(?<!after\s)\brain(ing|y)?\b",
    "after_rain": r"\bafter\s+rain\b",
    "peds": r"\bped(s|estrian)?\b|\bjaywalker\b",
    "cyclist": r"\bbicycl|\bbike\b|\bcyclist\b",
    "construction": r"\bconstruction\b",
    "intersection": r"\bintersection\b|\bcrosswalk\b",
    "turn": r"\bturn\b",
    "parked": r"\bparked\b|\bparking\s+lot\b",
    "bus": r"\bbus\b",
    "truck": r"\btruck\b",
    "hard_light": r"difficult lighting|glare",
}


def tags_of(description: str) -> list[str]:
    found = [k for k, p in TAG_RULES.items() if re.search(p, description, re.I)]
    # day는 명시되지 않는다 — night의 부재로 추론한다(§7.2)
    if "night" not in found:
        found.append("day_inferred")
    return sorted(found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataroot", type=Path, required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scenes", type=int, default=4, help="동시 재생할 장면 = 가상 차량 수")
    ap.add_argument("--window-ms", type=int, default=100)
    args = ap.parse_args()

    nusc = NuScenes(version=args.version, dataroot=str(args.dataroot), verbose=False)
    try:
        from nuscenes.can_bus.can_bus_api import NuScenesCanBus

        can = NuScenesCanBus(dataroot=str(args.dataroot))
    except Exception:
        can = None
        print("⚠️  CAN 없음 — 신호가 ego_pose로 축소된다")

    scenes = nusc.scene[: args.scenes]
    vehicles, clips = [], []
    # (t_rel_ms, vehicle_id, kind, payload) 를 모아 마지막에 시간순 배치로 만든다
    per_vehicle_batches: dict[str, list] = {}
    perception_events: list[dict] = []

    for i, scene in enumerate(scenes):
        vid = f"AV-{i + 1:04d}"
        log = nusc.get("log", scene["log_token"])
        signals = extract_native_signals(nusc, scene, vehicle_id=vid, can_api=can)
        extract = extract_scene(nusc, scene, vehicle_id=vid, can_api=can, include_sweeps=False)
        if not signals:
            continue

        t0 = signals[0].sensor_time
        # 모든 차량이 t=0에서 동시에 시작하도록 상대 시각으로 정규화한다.
        # 실제로는 각 차량이 제 시계를 쓰지만, 재생에서는 동시성을 만들어야 한다.
        rows = [
            {
                "event_id": s.event_id,
                "channel": s.channel,
                "t": (s.sensor_time - t0) // 1000,  # ms
                "v": s.values,
            }
            for s in signals
        ]

        batches = []
        for b in batch_by_window(
            [{**r, "sensor_time": r["t"] * 1000} for r in rows],
            vehicle_id=vid,
            window_us=args.window_ms * 1000,
        ):
            batches.append(
                {
                    "t": b.window_start // 1000,
                    "n": b.count,
                    "records": [
                        {"e": r["event_id"][-8:], "c": r["channel"], "t": r["t"], "v": r["v"]}
                        for r in b.records
                    ],
                }
            )
        per_vehicle_batches[vid] = batches

        # 인지 산출 — 키프레임 단위 요약 + 상위 클래스
        by_sample: dict[str, list] = defaultdict(list)
        for o in extract.perception:
            by_sample[o.sample_id].append(o)
        for sample_id, objs in by_sample.items():
            ts = (objs[0].sensor_time - t0) // 1000
            if ts < 0:
                continue
            cls = Counter(o.category.split(".")[1] if "." in o.category else o.category for o in objs)
            perception_events.append(
                {
                    "vehicle_id": vid,
                    "t": ts,
                    "n_objects": len(objs),
                    "n_zero_lidar": sum(1 for o in objs if o.num_lidar_pts == 0),
                    "classes": dict(cls.most_common(6)),
                    "boxes": [
                        {
                            "c": [round(o.center_x, 2), round(o.center_y, 2), round(o.center_z, 2)],
                            "s": [round(o.size_w, 2), round(o.size_l, 2), round(o.size_h, 2)],
                            "cat": o.category.split(".")[-1],
                            "lp": o.num_lidar_pts,
                            "vis": o.visibility,
                        }
                        for o in objs[:40]
                    ],
                }
            )

        lats = [s.values["lat"] for s in signals if s.channel == "ego_pose"]
        lons = [s.values["lon"] for s in signals if s.channel == "ego_pose"]
        vehicles.append(
            {
                "vehicle_id": vid,
                "scene_id": scene["token"],
                "scene_name": scene["name"],
                "location": log["location"],
                "description": scene["description"],
                "duration_ms": (signals[-1].sensor_time - t0) // 1000,
                "home": [round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6)],
            }
        )
        clips.append(
            {
                "clip_id": scene["name"],
                "vehicle_id": vid,
                "scene_name": scene["name"],
                "location": log["location"],
                "description": scene["description"],
                "tags": tags_of(scene["description"]),
                "duration_s": round((signals[-1].sensor_time - t0) / 1e6, 1),
                "n_objects": sum(1 for _ in extract.perception),
                "n_zero_lidar": sum(1 for o in extract.perception if o.num_lidar_pts == 0),
                "blob_uri": f"s3://fleetsentinel-bronze/mcap/{scene['name']}.mcap",
                "center": [round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6)],
                "bounds": [
                    [round(min(lats), 6), round(min(lons), 6)],
                    [round(max(lats), 6), round(max(lons), 6)],
                ],
            }
        )
        print(f"  {vid}  {scene['name']}  배치 {len(batches):>4}  신호 {len(signals):>6}  {log['location']}")

    args.out.mkdir(parents=True, exist_ok=True)
    duration = max(v["duration_ms"] for v in vehicles)
    (args.out / "meta.json").write_text(
        json.dumps(
            {
                "vehicles": vehicles,
                "duration_ms": duration,
                "window_ms": args.window_ms,
                "generated_from": f"{args.version} / {len(scenes)} scenes",
                "note": "실제 nuScenes 추출. 상대 시각(t=ms)으로 정규화해 동시 재생한다.",
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    (args.out / "batches.json").write_text(
        json.dumps(per_vehicle_batches, ensure_ascii=False, separators=(",", ":"))
    )
    perception_events.sort(key=lambda e: e["t"])
    (args.out / "perception.json").write_text(
        json.dumps(perception_events, ensure_ascii=False, separators=(",", ":"))
    )
    (args.out / "clips.json").write_text(json.dumps(clips, ensure_ascii=False, indent=1))

    total_batches = sum(len(b) for b in per_vehicle_batches.values())
    total_records = sum(bb["n"] for b in per_vehicle_batches.values() for bb in b)
    print(f"\n차량 {len(vehicles)}대 · 재생 {duration/1000:.1f}초")
    print(f"배치 {total_batches:,}건 · 레코드 {total_records:,}건")
    print(f"→ 재생 시 초당 배치 {total_batches/(duration/1000):.0f}건 / 레코드 {total_records/(duration/1000):.0f}건")
    for f in sorted(args.out.iterdir()):
        print(f"  {f.name:18s} {f.stat().st_size/1e6:6.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
