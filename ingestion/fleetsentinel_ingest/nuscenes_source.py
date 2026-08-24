"""nuScenes 장면(scene)에서 FleetSentinel 3계층 레코드를 추출한다.

계층 정의는 docs/data-design-v3.md §3–§4:
  ① 신호(signal)        — ego_pose + CAN bus, 수십 KB/s
  ② 인지 산출(perception) — 3D 박스, 키프레임 2Hz
  ③ 원시 센서(raw)       — 카메라/LiDAR/레이더, ~27.5 MB/s → Claim-Check 대상

CAN bus 확장은 별도 다운로드다(mini 기본 포함 아님 — R-V3-3). 없으면 신호 계층은
`ego_pose`만으로 축소되고 `steering_rad`/`yaw_rate`/`accel_*`는 None이 된다.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence

from ulid import ULID

from .geo import enu_to_wgs84

# CAN 채널별 샘플링 주기(실측): pose 50Hz, ms_imu 100Hz, steeranglefeedback 94Hz,
# vehicle_monitor 2Hz. 신호 레코드는 ego_pose(20Hz) 시각에 맞춰 최근접 결합한다.
CAN_POSE = "pose"
CAN_STEER = "steeranglefeedback"
CAN_IMU = "ms_imu"


@dataclass(frozen=True, slots=True)
class SignalRecord:
    """① 신호 계층 1건 — schemas/vehicle-signal.avsc 대응."""

    event_id: str
    vehicle_id: str
    scene_id: str
    sensor_time: int          # epoch microseconds (센서 자체 클럭)
    log_time: int             # 온보드 기록 시각
    pos_x: float
    pos_y: float
    pos_z: float
    quat_w: float
    quat_x: float
    quat_y: float
    quat_z: float
    lat: Optional[float]
    lon: Optional[float]
    location: str
    speed_mps: Optional[float] = None
    accel_x: Optional[float] = None
    accel_y: Optional[float] = None
    accel_z: Optional[float] = None
    steering_rad: Optional[float] = None
    yaw_rate: Optional[float] = None


@dataclass(frozen=True, slots=True)
class PerceptionRecord:
    """② 인지 산출 1건 — schemas/perception-object.avsc 대응."""

    event_id: str
    scene_id: str
    sample_id: str
    vehicle_id: str
    sensor_time: int
    track_id: str
    category: str
    attribute: Optional[str]
    center_x: float
    center_y: float
    center_z: float
    size_w: float
    size_l: float
    size_h: float
    rot_w: float
    rot_x: float
    rot_y: float
    rot_z: float
    visibility: str
    num_lidar_pts: int
    num_radar_pts: int


@dataclass(frozen=True, slots=True)
class ChannelSignal:
    """① 신호 1건을 **채널 네이티브 주기 그대로** 담는다.

    `SignalRecord`(ego_pose 시각에 CAN을 최근접 결합)는 조회 편의를 위한 파생형이고,
    이쪽이 무손실 정본이다. 결합형만 쓰면 `zoesensors` 955Hz가 20Hz로 깎여
    **98%가 버려진다** — 신호 계층에도 무손실 원칙이 적용돼야 한다.
    """

    event_id: str
    vehicle_id: str
    scene_id: str
    channel: str
    sensor_time: int
    values: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class RawSample:
    """③ 원시 센서 1건 — MCAP에 바이너리로 실리는 대상."""

    channel: str
    sensor_time: int
    filename: str
    is_key_frame: bool


@dataclass
class SceneExtract:
    """한 장면에서 뽑아낸 3계층 + 메타."""

    scene_id: str
    scene_name: str
    description: str
    location: str
    vehicle_id: str
    t_start: int
    t_end: int
    signals: List[SignalRecord] = field(default_factory=list)
    perception: List[PerceptionRecord] = field(default_factory=list)
    raw: List[RawSample] = field(default_factory=list)
    calibration: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    """채널별 센서 외부/내부 파라미터. 이게 없으면 MCAP만으로 3D 재생이 불가능하다
    (LiDAR는 센서 프레임, 3D 박스는 글로벌 프레임이라 정렬되지 않는다)."""


# 신호 계층에 싣는 CAN 채널. 실측 주기는 docs/data-design-v3.md §3.1.
NATIVE_CAN_CHANNELS = (
    "zoesensors",           # ~955Hz — 페달·조향 원시 센서
    "ms_imu",               # ~100Hz
    "zoe_veh_info",         # ~100Hz
    "steeranglefeedback",   # ~98Hz
    "pose",                 # ~50Hz
    "vehicle_monitor",      # ~2Hz
)


def extract_native_signals(
    nusc: Any,
    scene: Dict[str, Any],
    vehicle_id: str,
    can_api: Any = None,
    ego_channel: str = "LIDAR_TOP",
) -> List[ChannelSignal]:
    """장면의 신호를 **채널 네이티브 주기 그대로** 뽑는다(무손실).

    CAN이 없으면 `ego_pose`만 나온다. 결과는 `sensor_time` 오름차순이다.
    """
    scene_id = scene["token"]
    location = nusc.get("log", scene["log_token"])["location"]
    out: List[ChannelSignal] = []

    if can_api is not None:
        for channel in NATIVE_CAN_CHANNELS:
            try:
                messages = can_api.get_messages(scene["name"], channel)
            except Exception:
                continue  # 장면별 CAN 결손(공식 blacklist) — 무시하고 진행
            for msg in messages:
                values = {k: v for k, v in msg.items() if k != "utime"}
                out.append(
                    ChannelSignal(
                        event_id=str(ULID()),
                        vehicle_id=vehicle_id,
                        scene_id=scene_id,
                        channel=channel,
                        sensor_time=int(msg["utime"]),
                        values=values,
                    )
                )

    for sd in _iter_sample_data(nusc, scene, ego_channel):
        ego = nusc.get("ego_pose", sd["ego_pose_token"])
        lat, lon = enu_to_wgs84(ego["translation"][0], ego["translation"][1], location)
        out.append(
            ChannelSignal(
                event_id=str(ULID()),
                vehicle_id=vehicle_id,
                scene_id=scene_id,
                channel="ego_pose",
                sensor_time=int(ego["timestamp"]),
                values={
                    "translation": [float(v) for v in ego["translation"]],
                    "rotation": [float(v) for v in ego["rotation"]],
                    "lat": lat,
                    "lon": lon,
                    "location": location,
                },
            )
        )

    out.sort(key=lambda r: r.sensor_time)
    return out


class _NearestSeries:
    """정렬된 (utime, payload) 시계열에서 최근접 값을 찾는다."""

    def __init__(self, messages: Sequence[Dict[str, Any]]) -> None:
        ordered = sorted(messages, key=lambda m: m["utime"])
        self._times = [m["utime"] for m in ordered]
        self._items = ordered

    def at(self, utime: int) -> Optional[Dict[str, Any]]:
        if not self._times:
            return None
        i = bisect.bisect_left(self._times, utime)
        if i == 0:
            return self._items[0]
        if i >= len(self._times):
            return self._items[-1]
        before, after = self._times[i - 1], self._times[i]
        return self._items[i - 1] if utime - before <= after - utime else self._items[i]


def _load_can(can_api: Any, scene_name: str, channel: str) -> _NearestSeries:
    if can_api is None:
        return _NearestSeries([])
    try:
        return _NearestSeries(can_api.get_messages(scene_name, channel))
    except Exception:
        # 장면별로 CAN 데이터가 빠진 경우가 있다(공식 blacklist). 신호는 ego_pose로만 채운다.
        return _NearestSeries([])


def extract_scene(
    nusc: Any,
    scene: Dict[str, Any],
    vehicle_id: str,
    can_api: Any = None,
    ego_channel: str = "LIDAR_TOP",
    include_sweeps: bool = True,
) -> SceneExtract:
    """장면 하나를 3계층 레코드로 분해한다.

    :param vehicle_id: 재생기가 배분한 **가상** 차량 id (R-V3-5 — 실차량 아님)
    :param ego_channel: ego_pose를 샘플링할 기준 센서(LIDAR_TOP = 20Hz)
    :param include_sweeps: 원시 센서에 스윕(비키프레임)을 포함할지. **기본 True**가
        무손실 계약이다. False는 빠른 검증용 경량 모드이며 원시의 약 86%가 빠진다.
    """
    log = nusc.get("log", scene["log_token"])
    location = log["location"]
    scene_id = scene["token"]

    pose_series = _load_can(can_api, scene["name"], CAN_POSE)
    steer_series = _load_can(can_api, scene["name"], CAN_STEER)
    imu_series = _load_can(can_api, scene["name"], CAN_IMU)

    out = SceneExtract(
        scene_id=scene_id,
        scene_name=scene["name"],
        description=scene["description"],
        location=location,
        vehicle_id=vehicle_id,
        t_start=0,
        t_end=0,
    )

    # --- ① 신호: ego_channel의 sample_data 체인 전체를 훑는다(키프레임 아닌 것 포함).
    # 키프레임만 쓰면 2Hz라 신호 계층으로 너무 성기다. LIDAR_TOP 체인은 실측 ~20Hz.
    times: List[int] = []
    for sd in _iter_sample_data(nusc, scene, ego_channel):
        ego = nusc.get("ego_pose", sd["ego_pose_token"])
        utime = ego["timestamp"]
        times.append(utime)

        lat, lon = enu_to_wgs84(ego["translation"][0], ego["translation"][1], location)
        pose = pose_series.at(utime)
        steer = steer_series.at(utime)
        imu = imu_series.at(utime)

        speed = None
        accel = (None, None, None)
        if pose is not None:
            vel = pose.get("vel") or []
            speed = float(sum(v * v for v in vel) ** 0.5) if vel else None
            acc = pose.get("accel") or []
            if len(acc) == 3:
                accel = (float(acc[0]), float(acc[1]), float(acc[2]))

        yaw_rate = None
        if imu is not None and len(imu.get("rotation_rate") or []) == 3:
            yaw_rate = float(imu["rotation_rate"][2])

        q = ego["rotation"]
        out.signals.append(
            SignalRecord(
                event_id=str(ULID()),
                vehicle_id=vehicle_id,
                scene_id=scene_id,
                sensor_time=utime,
                log_time=sd["timestamp"],
                pos_x=float(ego["translation"][0]),
                pos_y=float(ego["translation"][1]),
                pos_z=float(ego["translation"][2]),
                quat_w=float(q[0]),
                quat_x=float(q[1]),
                quat_y=float(q[2]),
                quat_z=float(q[3]),
                lat=lat,
                lon=lon,
                location=location,
                speed_mps=speed,
                accel_x=accel[0],
                accel_y=accel[1],
                accel_z=accel[2],
                steering_rad=float(steer["value"]) if steer is not None else None,
                yaw_rate=yaw_rate,
            )
        )

    # --- ③ 원시 센서: 전 채널의 sample_data 체인 전체.
    # 키프레임만 담으면 sample_data의 15.5%, 바이트로는 13.6%만 남아 §9 무손실 원칙과
    # 어긋난다(SDD L-10). 스윕(비키프레임)을 포함해야 원본 보존이 성립한다.
    first_sample = nusc.get("sample", scene["first_sample_token"])
    for channel in sorted(first_sample["data"]):
        for sd in _iter_sample_data(nusc, scene, channel):
            if not include_sweeps and not sd["is_key_frame"]:
                continue
            if channel not in out.calibration:
                cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
                out.calibration[channel] = {
                    "channel": channel,
                    "translation": [float(v) for v in cs["translation"]],
                    "rotation": [float(v) for v in cs["rotation"]],
                    "camera_intrinsic": [
                        [float(v) for v in row] for row in (cs["camera_intrinsic"] or [])
                    ],
                    "width": sd.get("width"),
                    "height": sd.get("height"),
                    "fileformat": sd.get("fileformat"),
                }
            out.raw.append(
                RawSample(
                    channel=channel,
                    sensor_time=sd["timestamp"],
                    filename=sd["filename"],
                    is_key_frame=sd["is_key_frame"],
                )
            )

    for sample in _iter_samples(nusc, scene):
        # --- ② 인지 산출: 이 키프레임의 3D 박스 ---
        for ann_token in sample["anns"]:
            ann = nusc.get("sample_annotation", ann_token)
            attrs = [nusc.get("attribute", a)["name"] for a in ann["attribute_tokens"]]
            vis = nusc.get("visibility", ann["visibility_token"])["level"]
            out.perception.append(
                PerceptionRecord(
                    event_id=str(ULID()),
                    scene_id=scene_id,
                    sample_id=sample["token"],
                    vehicle_id=vehicle_id,
                    sensor_time=sample["timestamp"],
                    track_id=ann["instance_token"],
                    category=ann["category_name"],
                    attribute=attrs[0] if attrs else None,
                    center_x=float(ann["translation"][0]),
                    center_y=float(ann["translation"][1]),
                    center_z=float(ann["translation"][2]),
                    size_w=float(ann["size"][0]),
                    size_l=float(ann["size"][1]),
                    size_h=float(ann["size"][2]),
                    rot_w=float(ann["rotation"][0]),
                    rot_x=float(ann["rotation"][1]),
                    rot_y=float(ann["rotation"][2]),
                    rot_z=float(ann["rotation"][3]),
                    visibility=vis,
                    num_lidar_pts=int(ann["num_lidar_pts"]),
                    num_radar_pts=int(ann["num_radar_pts"]),
                )
            )

    out.t_start, out.t_end = (min(times), max(times)) if times else (0, 0)
    return out


def _iter_samples(nusc: Any, scene: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """장면의 키프레임(sample)을 시간순으로 순회한다 — 실측 ~2Hz."""
    token = scene["first_sample_token"]
    while token:
        sample = nusc.get("sample", token)
        yield sample
        token = sample["next"]


def _iter_sample_data(nusc: Any, scene: Dict[str, Any], channel: str) -> Iterator[Dict[str, Any]]:
    """한 채널의 sample_data 체인을 장면 끝까지 순회한다(비키프레임 포함).

    첫 키프레임의 해당 채널에서 시작해 `next`를 따라가되, 장면 마지막 키프레임의
    타임스탬프를 넘어서면 멈춘다(sample_data 체인은 로그 단위라 장면 경계를 넘는다).
    """
    first = nusc.get("sample", scene["first_sample_token"])
    last = nusc.get("sample", scene["last_sample_token"])
    end_time = nusc.get("sample_data", last["data"][channel])["timestamp"]

    token = first["data"][channel]
    while token:
        sd = nusc.get("sample_data", token)
        if sd["timestamp"] > end_time:
            return
        yield sd
        token = sd["next"]
