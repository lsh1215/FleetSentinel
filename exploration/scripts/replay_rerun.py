#!/usr/bin/env python3
"""MCAP → Rerun 재생 (P1 최종 게이트).

**MCAP 파일만 읽어서** 재생한다 — nuScenes devkit이나 원본 데이터셋을 참조하지 않는다.
이게 성립해야 "Bronze MCAP = 재생 가능한 무손실 원본"(docs/data-design-v3.md §9.1)이
말이 된다.

재생 구성:
    world/ego                  ego 차량 자세 (신호 계층)
    world/ego/<CAM_*>          카메라 6대 (Pinhole + JPEG)
    world/ego/LIDAR_TOP        LiDAR 포인트클라우드
    world/objects              인지 3D 박스 (글로벌 프레임)
    world/trajectory           누적 주행 궤적
    signals/*                  속도·조향각·yaw rate 시계열

사용:
    PYTHONPATH=. .venv/bin/python scripts/replay_rerun.py ../data/mcap/scene-0061.mcap \
        --out ../data/rrd/scene-0061.rrd
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import rerun as rr
from mcap.reader import make_reader
from pyquaternion import Quaternion

# nuScenes 카테고리 → 색. 상위 분류 기준으로 묶는다.
CATEGORY_COLORS: Dict[str, List[int]] = {
    "vehicle": [80, 160, 255],
    "human": [255, 90, 90],
    "movable_object": [250, 200, 60],
    "static_object": [150, 150, 150],
}
DEFAULT_COLOR = [200, 200, 200]

# nuScenes LIDAR .pcd.bin = float32 (x, y, z, intensity, ring) 5개씩
LIDAR_STRIDE = 5


def category_color(name: str) -> List[int]:
    return CATEGORY_COLORS.get(name.split(".")[0], DEFAULT_COLOR)


def nusc_quat(q: List[float]) -> rr.Quaternion:
    """nuScenes 쿼터니언 [w,x,y,z] → Rerun [x,y,z,w]."""
    return rr.Quaternion(xyzw=[q[1], q[2], q[3], q[0]])


def main() -> int:
    ap = argparse.ArgumentParser(description="MCAP → Rerun 재생")
    ap.add_argument("mcap", type=Path)
    ap.add_argument("--out", type=Path, help="저장할 .rrd 경로 (없으면 뷰어 spawn)")
    ap.add_argument("--max-lidar-points", type=int, default=40_000)
    args = ap.parse_args()

    rr.init("FleetSentinel — nuScenes replay", spawn=args.out is None)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        rr.save(str(args.out))

    rr.log("world", rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)

    stats = {"signal": 0, "perception": 0, "camera": 0, "lidar": 0, "calib": 0}
    trajectory: List[List[float]] = []
    calibrations: Dict[str, Dict[str, Any]] = {}

    with args.mcap.open("rb") as fp:
        reader = make_reader(fp)

        # 1) 캘리브레이션을 먼저 읽어 센서 프레임을 세운다.
        for _, _, message in reader.iter_messages(topics=["/tf/calibration"]):
            calib = json.loads(message.data)
            calibrations[calib["channel"]] = calib
            entity = f"world/ego/{calib['channel']}"
            rr.log(
                entity,
                rr.Transform3D(
                    translation=calib["translation"], quaternion=nusc_quat(calib["rotation"])
                ),
                static=True,
            )
            intr = calib.get("camera_intrinsic") or []
            if intr and calib.get("width"):
                rr.log(
                    entity,
                    rr.Pinhole(
                        image_from_camera=np.array(intr, dtype=np.float64),
                        resolution=[calib["width"], calib["height"]],
                        camera_xyz=rr.ViewCoordinates.RDF,
                    ),
                    static=True,
                )
            stats["calib"] += 1

        # 2) 시간순 재생
        for _, channel, message in reader.iter_messages():
            topic = channel.topic
            rr.set_time("sensor_time", timestamp=message.log_time / 1e9)

            if topic == "/vehicle/signal":
                rec = json.loads(message.data)
                pos = [rec["pos_x"], rec["pos_y"], rec["pos_z"]]
                rr.log(
                    "world/ego",
                    rr.Transform3D(
                        translation=pos,
                        quaternion=nusc_quat(
                            [rec["quat_w"], rec["quat_x"], rec["quat_y"], rec["quat_z"]]
                        ),
                    ),
                )
                trajectory.append(pos)
                if len(trajectory) > 1:
                    rr.log(
                        "world/trajectory",
                        rr.LineStrips3D([trajectory], colors=[[0, 220, 160]], radii=[0.25]),
                    )
                for key in ("speed_mps", "steering_rad", "yaw_rate"):
                    if rec.get(key) is not None:
                        rr.log(f"signals/{key}", rr.Scalars(rec[key]))
                if rec.get("lat") is not None:
                    rr.log("signals/lat", rr.Scalars(rec["lat"]))
                    rr.log("signals/lon", rr.Scalars(rec["lon"]))
                stats["signal"] += 1

            elif topic == "/perception/objects":
                payload = json.loads(message.data)
                objs = payload["objects"]
                if not objs:
                    continue
                rr.log(
                    "world/objects",
                    rr.Boxes3D(
                        centers=[[o["center_x"], o["center_y"], o["center_z"]] for o in objs],
                        # nuScenes size = (width, length, height) → half_sizes (x=l, y=w, z=h)/2
                        half_sizes=[
                            [o["size_l"] / 2, o["size_w"] / 2, o["size_h"] / 2] for o in objs
                        ],
                        quaternions=[
                            nusc_quat([o["rot_w"], o["rot_x"], o["rot_y"], o["rot_z"]])
                            for o in objs
                        ],
                        colors=[category_color(o["category"]) for o in objs],
                        labels=[o["category"].split(".")[-1] for o in objs],
                        show_labels=False,
                    ),
                )
                stats["perception"] += len(objs)

            elif topic.startswith("/camera/"):
                rr.log(
                    f"world/ego/{topic.rsplit('/', 1)[-1]}",
                    rr.EncodedImage(contents=message.data, media_type="image/jpeg"),
                )
                stats["camera"] += 1

            elif topic.startswith("/lidar/"):
                pts = np.frombuffer(message.data, dtype=np.float32)
                usable = (pts.size // LIDAR_STRIDE) * LIDAR_STRIDE
                cloud = pts[:usable].reshape(-1, LIDAR_STRIDE)
                xyz, intensity = cloud[:, :3], cloud[:, 3]
                if xyz.shape[0] > args.max_lidar_points:
                    idx = np.linspace(0, xyz.shape[0] - 1, args.max_lidar_points).astype(int)
                    xyz, intensity = xyz[idx], intensity[idx]
                shade = np.clip(intensity / 64.0, 0.0, 1.0)
                colors = np.stack(
                    [40 + 215 * shade, 120 + 100 * shade, 255 - 120 * shade], axis=1
                ).astype(np.uint8)
                rr.log(
                    f"world/ego/{topic.rsplit('/', 1)[-1]}/points",
                    rr.Points3D(xyz, colors=colors, radii=0.04),
                )
                stats["lidar"] += 1

    print(f"재생 로그 완료: {args.mcap.name}")
    print(f"  캘리브레이션 {stats['calib']}채널 · 신호 {stats['signal']} · "
          f"인지객체 {stats['perception']} · 카메라 {stats['camera']} · LiDAR {stats['lidar']}")
    if args.out:
        size = args.out.stat().st_size / 1e6
        print(f"  → {args.out} ({size:.1f}MB)")
        print(f"  열기: .venv/bin/rerun {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
