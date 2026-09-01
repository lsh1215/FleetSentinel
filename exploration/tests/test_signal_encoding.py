"""신호 레코드가 `schemas/vehicle-signal.avsc` 계약을 만족하는가.

여기서 지키는 것은 **채널 네이티브**다. 결합형(`SignalRecord`)으로 되돌아가면
`zoesensors` 943.8Hz가 19.7Hz로 깎여 신호의 98.5%가 사라진다
([데이터 설계](../../docs/data-design.md) §4.2). 그 회귀를 잡는 것이 이 파일의 목적이다.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import fastavro
import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO / "schemas"


def _load_shipper_module():
    spec = importlib.util.spec_from_file_location(
        "ship_to_gateway", REPO / "exploration" / "scripts" / "ship_to_gateway.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def mod():
    return _load_shipper_module()


@pytest.fixture(scope="module")
def signal_schema():
    return fastavro.parse_schema(
        json.loads((SCHEMA_DIR / "vehicle-signal.avsc").read_text()))


class _Sig:
    """ChannelSignal 대역. 데이터셋 없이 계약만 검사한다."""

    def __init__(self, channel, values):
        self.scene_id = "scene-x"
        self.channel = channel
        self.sensor_time = 1532402927649559
        self.values = values


class TestSchemaShape:
    def test_no_event_id(self, signal_schema):
        names = {f["name"] for f in signal_schema["fields"]}
        assert "event_id" not in names, "event_id는 (vehicle_id, boot_id, seq)로 대체됐다"

    def test_no_identity_in_payload(self, signal_schema):
        names = {f["name"] for f in signal_schema["fields"]}
        # 신원은 전송 봉투가 정본이다. 본문에 두 벌이면 하류가 어느 쪽을 믿느냐로 구멍이 열린다.
        assert "vehicle_id" not in names
        assert "boot_id" not in names

    def test_is_channel_native(self, signal_schema):
        names = {f["name"] for f in signal_schema["fields"]}
        assert "channel" in names, "채널 네이티브가 아니면 결합형이다"
        assert {"values_num", "values_vec", "values_str"} <= names
        # 결합형의 평탄화 필드가 남아 있으면 안 된다
        assert not (names & {"pos_x", "quat_w", "speed_mps", "steering_rad"})


class TestEncoding:
    def test_scalar_channel(self, mod, signal_schema):
        row = mod._signal_row(_Sig("zoesensors", {
            "brake_sensor": 0.1879, "steering_sensor": 0.1883, "throttle_sensor": 0.1209}))
        assert row["values_num"] == pytest.approx(
            {"brake_sensor": 0.1879, "steering_sensor": 0.1883, "throttle_sensor": 0.1209})
        assert row["values_vec"] == {} and row["values_str"] == {}
        assert _roundtrip(signal_schema, row)["channel"] == "zoesensors"

    def test_vector_channel(self, mod, signal_schema):
        row = mod._signal_row(_Sig("ms_imu", {
            "linear_accel": [-0.41, -0.48, 10.18],
            "q": [0.19, -0.009, -0.015, 0.98],
            "rotation_rate": [0.011, 0.027, 0.016]}))
        assert set(row["values_vec"]) == {"linear_accel", "q", "rotation_rate"}
        assert len(row["values_vec"]["q"]) == 4
        back = _roundtrip(signal_schema, row)
        assert back["values_vec"]["q"] == pytest.approx([0.19, -0.009, -0.015, 0.98])

    def test_mixed_channel_splits_by_type(self, mod, signal_schema):
        row = mod._signal_row(_Sig("ego_pose", {
            "translation": [411.3, 1180.9, 0.0],
            "rotation": [0.57, -0.0017, 0.0118, -0.82],
            "lat": 1.2988, "lon": 103.7884,
            "location": "singapore-onenorth"}))
        assert set(row["values_num"]) == {"lat", "lon"}
        assert set(row["values_vec"]) == {"translation", "rotation"}
        assert row["values_str"] == {"location": "singapore-onenorth"}
        _roundtrip(signal_schema, row)

    def test_int_widened_to_double(self, mod, signal_schema):
        # 정수 필드도 double 맵에 들어간다. 2^53 안이라 무손실이어야 한다.
        row = mod._signal_row(_Sig("vehicle_monitor", {
            "battery_level": 91, "gear_position": 7, "odom": 2_147_483_647}))
        back = _roundtrip(signal_schema, row)
        assert back["values_num"]["battery_level"] == 91.0
        assert back["values_num"]["odom"] == 2_147_483_647.0

    def test_none_becomes_absent_key(self, mod, signal_schema):
        # lat/lon 변환 실패는 키 부재로 표현한다(§5.1).
        row = mod._signal_row(_Sig("ego_pose", {"lat": None, "lon": None, "location": "x"}))
        assert "lat" not in row["values_num"] and "lon" not in row["values_num"]
        _roundtrip(signal_schema, row)

    def test_log_time_equals_sensor_time_in_replay(self, mod):
        # 재생기에는 별도의 온보드 클럭이 없다. 실차량에서만 둘이 갈린다.
        row = mod._signal_row(_Sig("zoesensors", {"brake_sensor": 0.1}))
        assert row["log_time"] == row["sensor_time"]


class TestPerceptionSchema:
    def test_no_event_id_or_identity(self):
        schema = json.loads((SCHEMA_DIR / "perception-object.avsc").read_text())
        names = {f["name"] for f in schema["fields"]}
        assert "event_id" not in names
        assert "vehicle_id" not in names


def _roundtrip(schema, row):
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, row)
    return fastavro.schemaless_reader(io.BytesIO(buf.getvalue()), schema)
