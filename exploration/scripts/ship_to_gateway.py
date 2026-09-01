#!/usr/bin/env python3
"""신호·인지 → WAL → gRPC 게이트웨이 → Kafka 종단 재생기.

지금까지 `LoopbackGateway`가 인프로세스로 대신하던 경로를 실제 네트워크로 돌린다.
바뀌는 것은 전송 계층뿐이다 — WAL·ack·dedup 계약은 그대로다.

    ┌──────────────┐   Avro    ┌─────┐   gRPC(mTLS)   ┌──────────┐  acks=all  ┌───────┐
    │ nuScenes     │──────────▶│ WAL │───────────────▶│ 게이트웨이 │───────────▶│ Kafka │
    │ 신호·인지     │           │ seq │◀── CACK ───────│ stateless │            └───────┘
    └──────────────┘           └─────┘   커밋 전진      └──────────┘

사용:
    PYTHONPATH=. .venv/bin/python scripts/ship_to_gateway.py \\
        --dataroot ../data/nuscenes --pki ../pki --vehicle vehicle-0001

    # 신원 바인딩 확인 — 인증서와 다른 ID를 주장하면 PERMISSION_DENIED로 끊긴다
    ... --claim vehicle-0002

원시 센서(③)는 이 경로를 타지 않는다 — 중량 경로는 오브젝트 스토리지 직행이다(SDD S-1).
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fleetsentinel_ingest.grpc_transport import (  # noqa: E402
    KIND_PERCEPTION,
    GrpcTransport,
    load_credentials,
)
from fleetsentinel_ingest.nuscenes_source import (  # noqa: E402
    extract_native_signals,
    extract_scene,
)
from fleetsentinel_ingest.shipping import WalShipper  # noqa: E402
from fleetsentinel_ingest.wal import KIND_SIGNAL, Wal  # noqa: E402

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _require_fastavro():
    """레코드 본문은 schemas/*.avsc 계약대로 Avro로 인코딩된다. 대체 포맷은 없다."""
    try:
        import fastavro
    except ImportError:
        raise SystemExit(
            "fastavro가 필요하다:\n"
            "  .venv/bin/pip install fastavro"
        )
    return fastavro


def _encode(fastavro: Any, schema: Any, record: dict) -> bytes:
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, record)
    return buf.getvalue()


def _signal_row(sig) -> dict:
    """ChannelSignal → vehicle-signal.avsc (채널 네이티브).

    **결합형(`SignalRecord`)을 쓰지 않는다.** 그쪽은 ego_pose 시각에 CAN을 최근접 결합한
    파생형이라 19.7Hz로 다운샘플되고, `zoesensors` 943.8Hz의 98.5%가 버려진다
    ([데이터 설계](../../docs/data-design.md) §4.2).

    값은 타입별 맵 3개로 나눈다 — Avro 맵 하나에 이종 타입을 담으려면 union이 필요하고,
    그러면 하류(Flink·ClickHouse)가 매 값마다 타입 분기를 해야 한다.

    `vehicle_id`가 없는 것은 의도적이다 — 신원은 전송 봉투(인증서 → Kafka 키)가 정본이고,
    본문에 두 벌을 두면 하류가 어느 쪽을 믿느냐에 따라 구멍이 열린다(SDD S-11).
    """
    num: dict = {}
    vec: dict = {}
    txt: dict = {}
    for k, v in sig.values.items():
        if v is None:
            continue          # 키 부재 = null. lat/lon 변환 실패가 이 경로다
        if isinstance(v, list):
            vec[k] = [float(x) for x in v]
        elif isinstance(v, str):
            txt[k] = v
        else:
            num[k] = float(v)  # 정수도 double로 넓힌다 — 전부 2^53 안이라 무손실
    return {
        "scene_id": sig.scene_id,
        "channel": sig.channel,
        "sensor_time": sig.sensor_time,
        # 원천에 온보드 기록 시각이 따로 없다. 재생기에는 buffering이 없으므로 같은 값을 쓴다.
        "log_time": sig.sensor_time,
        "values_num": num,
        "values_vec": vec,
        "values_str": txt,
    }


def _perception_row(rec) -> dict:
    return {
        "scene_id": rec.scene_id,
        "sample_id": rec.sample_id,
        "sensor_time": rec.sensor_time,
        "track_id": rec.track_id,
        "category": rec.category,
        "attribute": rec.attribute,
        "center_x": rec.center_x, "center_y": rec.center_y, "center_z": rec.center_z,
        "size_w": rec.size_w, "size_l": rec.size_l, "size_h": rec.size_h,
        "rot_w": rec.rot_w, "rot_x": rec.rot_x,
        "rot_y": rec.rot_y, "rot_z": rec.rot_z,
        "visibility": rec.visibility,
        "num_lidar_pts": rec.num_lidar_pts,
        "num_radar_pts": rec.num_radar_pts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pki", required=True, help="gen-certs.sh 의 PKI_DIR")
    ap.add_argument("--vehicle", default="vehicle-0001", help="쓸 인증서")
    ap.add_argument("--claim", default=None,
                    help="주장할 vehicle_id (기본: --vehicle과 동일). 다르게 주면 "
                         "게이트웨이가 PERMISSION_DENIED로 끊는다")
    ap.add_argument("--target", default="localhost:9090")
    ap.add_argument("--server-name", default="localhost")
    ap.add_argument("--dataroot", type=Path, default=Path("../data/nuscenes"))
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--scenes", type=int, default=1)
    ap.add_argument("--wal", type=Path, default=Path("./wal-run"))
    ap.add_argument("--keep-wal", action="store_true",
                    help="기존 WAL을 유지해 재개 동작을 본다")
    ap.add_argument("--stall-timeout", type=float, default=30.0,
                    help="전송·커밋 모두 이 시간(초) 동안 진전이 없으면 멈춘 것으로 본다")
    args = ap.parse_args()

    fastavro = _require_fastavro()
    signal_schema = fastavro.parse_schema(
        json.loads((SCHEMA_DIR / "vehicle-signal.avsc").read_text()))
    perception_schema = fastavro.parse_schema(
        json.loads((SCHEMA_DIR / "perception-object.avsc").read_text()))

    from nuscenes.nuscenes import NuScenes

    print(f"nuScenes 로드: {args.dataroot} ({args.version})")
    nusc = NuScenes(version=args.version, dataroot=str(args.dataroot), verbose=False)
    try:
        from nuscenes.can_bus.can_bus_api import NuScenesCanBus
        can = NuScenesCanBus(dataroot=str(args.dataroot))
    except Exception:
        can = None
        print("⚠️  CAN 없음 — 신호가 ego_pose로 축소된다")

    signals: List[Any] = []
    perception: List[Any] = []
    for scene in nusc.scene[: args.scenes]:
        # 신호는 채널 네이티브(무손실). 인지는 extract_scene 이 정본이다.
        signals.extend(extract_native_signals(nusc, scene, vehicle_id=args.vehicle,
                                              can_api=can))
        extract = extract_scene(nusc, scene, vehicle_id=args.vehicle,
                                can_api=can, include_sweeps=False)
        perception.extend(extract.perception)

    if not args.keep_wal and args.wal.exists():
        shutil.rmtree(args.wal)
    args.wal.mkdir(parents=True, exist_ok=True)

    wal = Wal(args.wal)
    # 재개(--keep-wal)에서는 seq가 0부터 시작하지 않는다. 기준선을 잡아두지 않으면
    # "몇 번까지 커밋돼야 성공인가"를 계산할 수 없다.
    first_new_seq = wal.next_seq
    resume_backlog = max(0, first_new_seq - 1 - wal.committed_seq)
    print(f"WAL: {args.wal}  boot_id={wal.boot_id}  committed={wal.committed_seq}"
          f"  next_seq={first_new_seq}")
    if resume_backlog:
        print(f"     재개: 미커밋 {resume_backlog:,}건이 남아 있다 — 이번에 함께 재전송된다")

    # ── ① WAL 적재 ──────────────────────────────────────────────────────
    t0 = time.monotonic()
    for rec in signals:
        wal.append(_encode(fastavro, signal_schema, _signal_row(rec)), kind=KIND_SIGNAL)
    for rec in perception:
        wal.append(_encode(fastavro, perception_schema, _perception_row(rec)),
                   kind=KIND_PERCEPTION)
    total_records = len(signals) + len(perception)
    t_wal = time.monotonic() - t0
    print(f"WAL 적재: 신호 {len(signals):,} · 인지 {len(perception):,} "
          f"= {total_records:,}건 ({total_records / max(t_wal, 1e-9):,.0f} rec/s)")

    if total_records == 0:
        print("보낼 레코드가 없다")
        return 1

    # ── ② 게이트웨이로 전송 ─────────────────────────────────────────────
    claim = args.claim or args.vehicle
    transport = GrpcTransport(
        target=args.target,
        credentials=load_credentials(args.pki, args.vehicle),
        vehicle_id=claim,
        server_name=args.server_name,
    )
    shipper = WalShipper(wal, transport)
    transport.set_ack_handler(shipper.on_ack)

    print(f"전송: target={args.target} cert={args.vehicle} claim={claim} "
          f"resume_from={shipper.resume_from}")

    # 이번 실행에서 보내야 할 총량 = 새로 적재한 것 + 재개 시 남아 있던 미커밋분.
    to_send = total_records + resume_backlog
    # 커밋이 여기까지 가면 "보낸 것 전부가 Kafka에 안전하게 들어갔다"가 성립한다.
    expected_commit = first_new_seq + total_records - 1

    t0 = time.monotonic()
    transport.start(wal.boot_id)

    # ack이 멈춰도 스트림은 안 끊긴다 — Kafka 쓰기 실패는 의도적으로 ack만 정지시킨다.
    # 그러면 pump()가 max_inflight 소진 후 0을 반환하고 terminal_error는 None이라,
    # 상한이 없으면 여기서 영원히 돈다.
    stall_limit = args.stall_timeout
    last_progress = time.monotonic()
    last_seen = (shipper.stats.sent, wal.committed_seq)
    stalled = False

    while shipper.stats.sent < to_send:
        if transport.stats.terminal_error:
            break
        if shipper.pump(budget=512) == 0:
            time.sleep(0.005)

        progress = (shipper.stats.sent, wal.committed_seq)
        if progress != last_seen:
            last_seen, last_progress = progress, time.monotonic()
        elif time.monotonic() - last_progress > stall_limit:
            stalled = True
            break

    if not stalled and not transport.stats.terminal_error:
        # 마지막 구간의 CACK을 기다린다. close()가 half-close 후 ack 리더를 join한다.
        transport.close()
    else:
        transport.close(timeout=5.0)
    elapsed = time.monotonic() - t0

    print()
    print(f"  전송        {shipper.stats.sent:,}건 (목표 {to_send:,})")
    print(f"  CACK 수신   {transport.stats.acks_received:,}회 · 최종 ack={transport.stats.last_ack}")
    print(f"  WAL 커밋    {wal.committed_seq}")
    print(f"  처리량      {shipper.stats.sent / max(elapsed, 1e-9):,.0f} rec/s")

    if stalled:
        print(f"  ⚠️ {stall_limit:.0f}초 동안 진전이 없다 — CACK이 멈췄다.")
        print(f"     게이트웨이가 Kafka에 못 쓰고 있을 가능성이 높다(ack은 쓰기 성공 뒤에만 "
              f"나간다). 게이트웨이 로그와 "
              f"fleetsentinel_gateway_records_failed_total 을 확인한다.")
        return 1

    if transport.stats.terminal_error:
        print(f"  스트림 종료: {transport.stats.terminal_error}")
        return 1

    if wal.committed_seq != expected_commit:
        print(f"  ⚠️ 커밋이 {expected_commit}까지 가지 않았다 (현재 {wal.committed_seq}) "
              f"— 미ack 구간이 남았다")
        return 1

    print("  ✅ 전량 CACK · 결번 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
