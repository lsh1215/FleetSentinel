# exploration — 데이터 측정·검증 + 차량 측 유실 방지 구현

> ## ⚠️ 성격이 다른 두 종류가 섞여 있다
>
> | | 목적 | 승격 가능? |
> |---|---|---|
> | **측정·검증 도구** | "어떤 데이터가 어떤 규모·형식으로 들어오는가"를 알아낸다 | ❌ 측정용이라 오류 처리·재시도·백프레셔가 없다 |
> | **차량 측 유실 방지** (`wal.py` · `shipping.py` · `dedup.py`) | 설계한 프로토콜이 **실제로 성립하는지 실증한다** | △ 설계는 유효, 구현은 재생기용 |
>
> 측정 결과는 [`../docs/data-design.md`](../docs/data-design.md)에만 있다.
> 유실 방지 설계는 [`../docs/wal-design.md`](../docs/wal-design.md) ·
> [`../docs/ack-dedup-design.md`](../docs/ack-dedup-design.md)에 있다.
>
> **`wal.py`·`shipping.py`·`dedup.py`는 탐색 코드가 아니다.** 문서의 설계를 그대로 구현해
> SIGKILL로 검증한 것이고, 실차량 온보드 소프트웨어가 아니라는 점만 다르다
> ([SDD](../docs/sdd.md) L-2·L-13). 나머지는 측정 도구이므로 그대로 승격시키지 말 것.

## 파일 성격

### 측정·검증 (문서 수치의 근거)

| 파일 | 역할 |
|---|---|
| `fleetsentinel_ingest/geo.py` | ENU ↔ WGS84 변환. **좌표 형식이 무엇인지 알아내기 위해** 구현했다 — `ego_pose`가 위경도가 아니라 로컬 미터라는 것, "보스턴 1.35배"가 Web Mercator 축척계수라는 것을 이걸로 규명했다 |
| `scripts/measure_batching.py` | 채널별 Hz·레코드 크기 실측. 문서 §3.1의 모든 수치가 여기서 나왔다 |
| `scripts/verify_mcap.py` | MCAP 유효성 + **무손실 계약** 검증. 원시 센서 86% 누락을 여기서 잡았다 |
| `scripts/replay_rerun.py` | 데이터를 눈으로 확인 |
| `scripts/export_fixture.py` | 대시보드용 픽스처 추출 — 목업 스트림이 난수가 아닌 근거 |

### 차량 측 유실 방지 (설계의 실증)

| 파일 | 역할 | 검증한 것 |
|---|---|---|
| `fleetsentinel_ingest/wal.py` | 온보드 WAL — 레코드 포맷·세그먼트·그룹 커밋·복구·커서 | **SIGKILL 후 `seq` 결번 0** |
| `fleetsentinel_ingest/shipping.py` | Cumulative Acknowledgement(CACK) 프로토콜 + 배송기 | ack이 **Kafka 쓰기 성공을 앞지르지 않음**, 역압 |
| `fleetsentinel_ingest/dedup.py` | `(vehicle_id, boot_id, seq)` 슬라이딩 윈도우 dedup | 상태가 **데이터 양에 비례하지 않음**, 순서 역전에서 유실 0 |

세 개를 이으면 **at-least-once 전송 + 멱등 dedup = 결과적 exactly-once** 다.
SIGKILL 후 재개해서 하류가 보는 것이 정확히 한 번인지 재전송량 예측치와 대조한다.

처리량·상태 크기 실측치는 [`../docs/wal-design.md`](../docs/wal-design.md) §3.10 ·
[`../docs/ack-dedup-design.md`](../docs/ack-dedup-design.md) §4가 정본이다 — 이 README는
수치를 적지 않는다.

### 탐색 도구 (재설계 대상)

| 파일 | 성격 | 비고 |
|---|---|---|
| `fleetsentinel_ingest/nuscenes_source.py` | 추출기 | |
| `fleetsentinel_ingest/mcap_writer.py` | MCAP 작성 | |
| `fleetsentinel_ingest/batching.py` | 전송 배치 정책 | ⚠️ **설계가 뒤집혔다** — 축적 창은 그만큼의 유실이다([설계 검토](../docs/ingestion-design-review.md) §4.1). 측정 하네스로만 남아 있다 |
| `scripts/convert_scenes.py` | 변환 CLI | |
| `scripts/measure_batching.py` | 채널 실측 | 이름이 배치를 가리키지만 측정하는 것은 채널별 Hz·크기다 |

### 테스트 82건

| 파일 | 건수 | 대상 |
|---|---|---|
| `tests/test_geo.py` | 30 | 좌표 변환 계약 (왕복·축방향·거리보존·원점) |
| `tests/test_wal.py` | 13 | WAL 내구성 — 잘린 꼬리·세그먼트 회수·SIGKILL·`seq` 재사용 방지 |
| `tests/test_dedup.py` | 14 | 멱등·순서 역전·`boot_id` 리셋·유실 확정·상태 크기 |
| `tests/test_shipping.py` | 13 | CACK·역압·SIGKILL 후 결과적 exactly-once |
| `tests/test_batching.py` | 12 | 뒤집힌 배치 정책의 계약 (측정 하네스) |

## 준비

```bash
./setup-venv.sh     # 2단계 설치 — 이유는 스크립트 주석 참고
```

**`pip install -r requirements.in`을 직접 쓰면 안 된다.** `nuscenes-devkit`이 `numpy<2`를
선언하는데 `rerun-sdk` 0.23은 numpy 2를 요구해서 pip이 거부한다. numpy 1.26에서는
쿼터니언이 **조용히 누락**되고 경고만 남아 회전이 빠진 재생본이 만들어진다.

데이터는 인증 없이 받을 수 있다. 비상업 라이선스이므로 레포에 커밋하지 않는다.

```bash
mkdir -p ../data/nuscenes && cd ../data/nuscenes
curl -LO https://d36yt3mvayqw5m.cloudfront.net/public/v1.0/v1.0-mini.tgz   # 4.17GB
tar -xzf v1.0-mini.tgz
curl -LO https://d36yt3mvayqw5m.cloudfront.net/public/v1.0/can_bus.zip     # 745MB
unzip -q can_bus.zip
```

## 실행

```bash
# 채널별 Hz·크기 실측 (문서 §3.1의 근거)
PYTHONPATH=. ./.venv/bin/python scripts/measure_batching.py --dataroot ../data/nuscenes

# nuScenes → MCAP 변환 (장면당 ~357MB)
PYTHONPATH=. ./.venv/bin/python scripts/convert_scenes.py \
    --dataroot ../data/nuscenes --out ../data/mcap --scenes 3 --vehicles 3

# 무손실 계약 검증 — dataroot를 주면 정본 sample_data와 대조한다
PYTHONPATH=. ./.venv/bin/python scripts/verify_mcap.py ../data/mcap ../data/nuscenes

# 재생본 생성 후 열기
PYTHONPATH=. ./.venv/bin/python scripts/replay_rerun.py \
    ../data/mcap/scene-0061.mcap --out ../data/rrd/scene-0061.rrd
./.venv/bin/rerun ../data/rrd/scene-0061.rrd

# 대시보드용 픽스처 추출
PYTHONPATH=. ./.venv/bin/python scripts/export_fixture.py \
    --dataroot ../data/nuscenes --out ../frontend/public/fixture --scenes 4

# 테스트 82건 — 데이터는 필요 없다 (SIGKILL 테스트가 있어 몇 초 걸린다)
PYTHONPATH=. ./.venv/bin/python -m pytest tests/ -q
```

## 알아낸 것

데이터 사실은 전부 [`../docs/data-design.md`](../docs/data-design.md)에 있다.
**이 README는 수치를 적지 않는다** — 같은 사실이 두 곳에 있으면 반드시 어긋난다.

측정 항목: 계층별 발생률·대역폭, 채널별 Hz·크기·형식, 좌표계 규명, 라벨 품질,
시나리오 태그 커버리지, 무손실 검증, 좌표 체인 종단 검증.
