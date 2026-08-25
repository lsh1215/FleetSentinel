"""SceneExtract를 MCAP 파일로 기록한다 — Bronze 원본 보존 포맷(§9.1).

MCAP을 고른 이유는 docs/data-design.md §9.1에 있다: 이종 타임스탬프 메시지를
채널별로 담고, **스키마를 파일에 내장**하며(self-describing), 인덱스가 있어 구간
랜덤 액세스가 된다. ROS 2 Iron부터 rosbag2 기본 포맷이다.

채널 구성:
  /vehicle/signal          jsonschema  ① 신호 (경량 — Kafka로도 흐른다)
  /perception/objects      jsonschema  ② 인지 산출 (경량)
  /camera/CAM_*            jpeg        ③ 원시 (중량 — Claim-Check 대상)
  /lidar/LIDAR_TOP         pcd-bin     ③ 원시
  /radar/RADAR_*           pcd         ③ 원시
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcap.writer import Writer

from .nuscenes_source import SceneExtract

US_TO_NS = 1000

SIGNAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "title": "VehicleSignal",
    "description": "FleetSentinel ① 신호 계층 — docs/data-design.md §4.1",
    "properties": {
        "event_id": {"type": "string", "description": "ULID, 멱등키"},
        "vehicle_id": {"type": "string", "description": "재생 배분 가상 차량 id"},
        "scene_id": {"type": "string"},
        "sensor_time": {"type": "integer", "description": "센서 클럭, epoch us"},
        "log_time": {"type": "integer", "description": "온보드 기록 시각, epoch us"},
        "pos_x": {"type": "number", "description": "ENU 동쪽(m)"},
        "pos_y": {"type": "number", "description": "ENU 북쪽(m)"},
        "pos_z": {"type": "number", "description": "nuScenes에서 항상 0"},
        "quat_w": {"type": "number"},
        "quat_x": {"type": "number"},
        "quat_y": {"type": "number"},
        "quat_z": {"type": "number"},
        "lat": {"type": ["number", "null"], "description": "WGS84 파생(§8)"},
        "lon": {"type": ["number", "null"]},
        "location": {"type": "string"},
        "speed_mps": {"type": ["number", "null"], "description": "CAN pose 없으면 null"},
        "accel_x": {"type": ["number", "null"]},
        "accel_y": {"type": ["number", "null"]},
        "accel_z": {"type": ["number", "null"]},
        "steering_rad": {"type": ["number", "null"]},
        "yaw_rate": {"type": ["number", "null"]},
    },
    "required": ["event_id", "vehicle_id", "scene_id", "sensor_time", "location"],
}

PERCEPTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "title": "PerceptionObjects",
    "description": "FleetSentinel ② 인지 산출 — 키프레임 1건의 3D 박스 배열 (§4.2)",
    "properties": {
        "sample_id": {"type": "string"},
        "sensor_time": {"type": "integer"},
        "objects": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["sample_id", "sensor_time", "objects"],
}

CALIBRATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "title": "SensorCalibration",
    "description": (
        "센서 외부/내부 파라미터. MCAP만으로 3D 재생이 성립하려면 반드시 있어야 한다 — "
        "LiDAR/레이더는 센서 프레임, 인지 3D 박스는 글로벌 프레임이라 이 변환 없이는 정렬되지 않는다."
    ),
    "properties": {
        "channel": {"type": "string"},
        "translation": {"type": "array", "items": {"type": "number"}, "description": "ego 기준 (x,y,z) m"},
        "rotation": {"type": "array", "items": {"type": "number"}, "description": "쿼터니언 (w,x,y,z)"},
        "camera_intrinsic": {"type": "array", "description": "카메라만 3x3, 그 외 빈 배열"},
        "width": {"type": ["integer", "null"]},
        "height": {"type": ["integer", "null"]},
    },
    "required": ["channel", "translation", "rotation"],
}

# 확장자 → (message_encoding, 채널 접두어)
_RAW_KIND = {
    ".jpg": ("jpeg", "/camera"),
    ".jpeg": ("jpeg", "/camera"),
    ".png": ("png", "/camera"),
    ".bin": ("application/octet-stream", "/lidar"),
    ".pcd": ("application/octet-stream", "/radar"),
}


def _raw_topic(channel: str, suffix: str) -> tuple[str, str]:
    encoding, prefix = _RAW_KIND.get(suffix, ("application/octet-stream", "/raw"))
    if channel.startswith("RADAR"):
        prefix = "/radar"
    elif channel.startswith("CAM"):
        prefix = "/camera"
    elif channel.startswith("LIDAR"):
        prefix = "/lidar"
    return f"{prefix}/{channel}", encoding


def write_scene_mcap(
    extract: SceneExtract,
    dataroot: Path,
    out_path: Path,
    include_raw: bool = True,
) -> Dict[str, Any]:
    """장면 하나를 MCAP 한 파일로 쓴다.

    :param include_raw: False면 ③ 원시 센서를 제외하고 경량 계층만 기록한다
        (대역폭 대비 실험·경량 카탈로그 생성용).
    :returns: segment-ref 메타(§4.3)에 쓸 요약 dict — 이 파일 자체가 '세그먼트'이고,
        돌려주는 dict은 그것을 **가리키는 참조**다(둘을 혼동하지 않도록 이름을 나눴다)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    channels_seen: List[str] = []

    with out_path.open("wb") as fp:
        writer = Writer(fp)
        writer.start(profile="fleetsentinel", library="fleetsentinel-ingest")

        signal_schema = writer.register_schema(
            name="fleetsentinel.VehicleSignal",
            encoding="jsonschema",
            data=json.dumps(SIGNAL_SCHEMA).encode(),
        )
        perception_schema = writer.register_schema(
            name="fleetsentinel.PerceptionObjects",
            encoding="jsonschema",
            data=json.dumps(PERCEPTION_SCHEMA).encode(),
        )
        signal_ch = writer.register_channel(
            topic="/vehicle/signal", message_encoding="json", schema_id=signal_schema
        )
        perception_ch = writer.register_channel(
            topic="/perception/objects", message_encoding="json", schema_id=perception_schema
        )
        calibration_schema = writer.register_schema(
            name="fleetsentinel.SensorCalibration",
            encoding="jsonschema",
            data=json.dumps(CALIBRATION_SCHEMA).encode(),
        )
        calibration_ch = writer.register_channel(
            topic="/tf/calibration", message_encoding="json", schema_id=calibration_schema
        )
        channels_seen += ["/vehicle/signal", "/perception/objects", "/tf/calibration"]

        # 캘리브레이션은 장면 시작 시각에 채널당 1건 — 재생기가 먼저 읽어 프레임을 세운다.
        for channel, calib in sorted(extract.calibration.items()):
            writer.add_message(
                channel_id=calibration_ch,
                log_time=extract.t_start * US_TO_NS,
                publish_time=extract.t_start * US_TO_NS,
                data=json.dumps(calib).encode(),
            )

        # ① 신호
        for sig in extract.signals:
            writer.add_message(
                channel_id=signal_ch,
                log_time=sig.sensor_time * US_TO_NS,
                publish_time=sig.sensor_time * US_TO_NS,
                data=json.dumps(dataclasses.asdict(sig)).encode(),
            )

        # ② 인지 산출 — 키프레임 단위로 묶는다
        by_sample: Dict[str, List[Dict[str, Any]]] = {}
        sample_time: Dict[str, int] = {}
        for obj in extract.perception:
            by_sample.setdefault(obj.sample_id, []).append(dataclasses.asdict(obj))
            sample_time[obj.sample_id] = obj.sensor_time
        for sample_id, objs in by_sample.items():
            ts = sample_time[sample_id]
            writer.add_message(
                channel_id=perception_ch,
                log_time=ts * US_TO_NS,
                publish_time=ts * US_TO_NS,
                data=json.dumps(
                    {"sample_id": sample_id, "sensor_time": ts, "objects": objs}
                ).encode(),
            )

        # ③ 원시 센서 — 파일 바이트를 그대로 싣는다(무손실 보존)
        raw_bytes = 0
        if include_raw:
            raw_channels: Dict[str, int] = {}
            for sample in extract.raw:
                path = dataroot / sample.filename
                if not path.exists():
                    continue
                topic, encoding = _raw_topic(sample.channel, path.suffix.lower())
                if topic not in raw_channels:
                    raw_channels[topic] = writer.register_channel(
                        topic=topic, message_encoding=encoding, schema_id=0
                    )
                    channels_seen.append(topic)
                payload = path.read_bytes()
                raw_bytes += len(payload)
                writer.add_message(
                    channel_id=raw_channels[topic],
                    log_time=sample.sensor_time * US_TO_NS,
                    publish_time=sample.sensor_time * US_TO_NS,
                    data=payload,
                )

        writer.finish()

    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return {
        "segment_scene_id": extract.scene_id,
        "scene_name": extract.scene_name,
        "vehicle_id": extract.vehicle_id,
        "blob_uri": str(out_path),
        "t_start": extract.t_start,
        "t_end": extract.t_end,
        "sensor_channels": sorted(set(channels_seen)),
        "size_bytes": out_path.stat().st_size,
        "checksum": f"sha256:{digest}",
        "sample_count": len(extract.signals),
        "n_signals": len(extract.signals),
        "n_perception": len(extract.perception),
        "n_raw": len(extract.raw),
        "n_raw_keyframe": sum(1 for r in extract.raw if r.is_key_frame),
        "n_raw_sweep": sum(1 for r in extract.raw if not r.is_key_frame),
        "raw_bytes": raw_bytes,
        "location": extract.location,
        "description": extract.description,
    }
