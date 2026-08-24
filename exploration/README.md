# exploration — P1 데이터 탐색 산출물

> ## ⚠️ 이 디렉터리는 파이프라인 구현이 아니다
>
> **목적은 하나다 — "어떤 데이터가 어떤 규모·형식으로 들어오는가"를 알아내는 것.**
> 그 답은 [`../docs/data-design-v3.md`](../docs/data-design-v3.md)에 있고, 여기 있는
> 코드는 **그 문서의 수치를 뽑아낸 도구이자 근거**다.
>
> 데이터 수집·ETL·전송 파이프라인은 **아직 설계하지 않았다.** 여기 있는 추출기·
> MCAP 작성기·배치 모듈은 측정을 위해 만든 탐색 코드이고, **프로덕션 파이프라인은
> 별도로 설계한다.** 이 코드를 그대로 승격시키지 말 것 — 측정이 목적이라
> 오류 처리·재시도·백프레셔·스키마 진화가 전부 빠져 있다.

## 파일 성격

### 측정·검증 (문서 수치의 근거)

| 파일 | 역할 |
|---|---|
| `fleetsentinel_ingest/geo.py` | ENU ↔ WGS84 변환. **좌표 형식이 무엇인지 알아내기 위해** 구현했다 — `ego_pose`가 위경도가 아니라 로컬 미터라는 것, "보스턴 1.35배"가 Web Mercator 축척계수라는 것을 이걸로 규명했다 |
| `scripts/measure_batching.py` | 채널별 Hz·레코드 크기 실측. 문서 §3.1의 모든 수치가 여기서 나왔다 |
| `scripts/verify_mcap.py` | MCAP 유효성 + **무손실 계약** 검증. 원시 센서 86% 누락을 여기서 잡았다 |
| `scripts/replay_rerun.py` | 데이터를 눈으로 확인 |
| `tests/` | 좌표·배치 계약 테스트 42건 |

### 탐색 도구 (파이프라인 구현이 아님)

| 파일 | 성격 | 파이프라인 설계 시 |
|---|---|---|
| `fleetsentinel_ingest/nuscenes_source.py` | 추출기 | 재설계 대상 |
| `fleetsentinel_ingest/mcap_writer.py` | MCAP 작성 | 재설계 대상 |
| `fleetsentinel_ingest/batching.py` | 전송 배치 정책 | **전송 설계 영역** — 잠정 |
| `scripts/convert_scenes.py` | 변환 CLI | 재설계 대상 |

`batching.py`와 그 테스트는 성격상 데이터 정의가 아니라 **전송 설계**다. 측정을 위해
먼저 만들었고, 결과는 [`../docs/pipeline-notes-provisional.md`](../docs/pipeline-notes-provisional.md)에
잠정 기록으로 분리해 뒀다.

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

# 테스트
PYTHONPATH=. ./.venv/bin/python -m pytest tests/ -q
```

## 알아낸 것 (요약)

전체는 [`../docs/data-design-v3.md`](../docs/data-design-v3.md)에 있다.

| 항목 | 결과 |
|---|---|
| 계층 구조 | 신호 1,295 rec/s(432 KB/s) · 인지 2.1/s · 원시 159 파일/s(**27.15 MB/s**) |
| 최고 주기 채널 | **`zoesensors` 937Hz** (간격 0.25ms) — 초안이 `ms_imu` 100Hz로 잘못 적었던 부분 |
| 좌표계 | ENU 로컬 미터(z=0). "보스턴 1.35배"는 Web Mercator 축척계수 `1/cos(42.34°)` |
| 라벨 품질 | `num_lidar_pts=0`이 **23.1%** (18,538건 중 4,278건) |
| 시나리오 태그 | 보행자 8/10, 야간 3/10, **활성 강우 1/10**, 주간 명시 **0/10** |
| 무손실 검증 | 정본 대조 3장면 누락 0 (2,963 / 3,063 / 3,171) |
| 좌표 종단 검증 | 박스 내 LiDAR 포인트 대조 **31,911개 오차 0** |
