# ingestion — nuScenes 실측 멀티모달 수집 계층 (P1)

FleetSentinel v3.0의 데이터 원천. nuScenes 실측 데이터를 판독해 3계층 레코드로
분해하고, Bronze 원본 포맷(MCAP)으로 변환하고, Rerun으로 재생한다.

설계 정본은 [`../docs/data-design-v3.md`](../docs/data-design-v3.md).

## 준비

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

nuScenes mini(4.17GB)와 CAN bus 확장(745MB)은 **인증 없이** 받을 수 있다.
비상업 라이선스이므로 레포에 커밋하지 않는다(`.gitignore` 등록됨).

```bash
mkdir -p ../data/nuscenes && cd ../data/nuscenes
curl -LO https://d36yt3mvayqw5m.cloudfront.net/public/v1.0/v1.0-mini.tgz
tar -xzf v1.0-mini.tgz
curl -LO https://d36yt3mvayqw5m.cloudfront.net/public/v1.0/can_bus.zip
unzip -q can_bus.zip
```

## 사용

```bash
# 1) nuScenes → MCAP 변환 (장면을 N대 가상 차량에 배분)
PYTHONPATH=. ./.venv/bin/python scripts/convert_scenes.py \
    --dataroot ../data/nuscenes --out ../data/mcap --scenes 3 --vehicles 3

# 2) MCAP 유효성 검증 (인덱스·스키마·메시지 수·구간 랜덤 액세스)
PYTHONPATH=. ./.venv/bin/python scripts/verify_mcap.py ../data/mcap

# 3) MCAP → Rerun 재생본 생성
PYTHONPATH=. ./.venv/bin/python scripts/replay_rerun.py \
    ../data/mcap/scene-0061.mcap --out ../data/rrd/scene-0061.rrd

# 4) 재생본 열기 (또는 --out 없이 실행하면 뷰어가 바로 뜬다)
./.venv/bin/rerun ../data/rrd/scene-0061.rrd

# 테스트
PYTHONPATH=. ./.venv/bin/python -m pytest tests/ -q
```

## MCAP 채널 구성

`replay_rerun.py`는 **MCAP만 읽는다** — devkit도 원본 데이터셋도 참조하지 않는다.
이게 성립해야 "Bronze MCAP = 재생 가능한 무손실 원본"(§9.1)이 말이 된다.

| 채널 | 인코딩 | 계층 |
|---|---|---|
| `/vehicle/signal` | jsonschema | ① 신호 — ego pose + CAN, 실측 ~20Hz |
| `/perception/objects` | jsonschema | ② 인지 산출 — 키프레임 2Hz의 3D 박스 배열 |
| `/tf/calibration` | jsonschema | 센서 외부/내부 파라미터 (채널당 1건, 정적) |
| `/camera/CAM_*` | jpeg | ③ 원시 — 카메라 6대 |
| `/lidar/LIDAR_TOP` | octet-stream | ③ 원시 — float32 (x,y,z,intensity,ring) |
| `/radar/RADAR_*` | octet-stream | ③ 원시 — 레이더 5대 |

> `/tf/calibration`이 없으면 MCAP만으로 3D 재생이 **불가능**하다. LiDAR는 센서 프레임,
> 인지 3D 박스는 글로벌 프레임이라 변환 없이는 정렬되지 않는다. P1에서 발견해 추가했다.

## 의존성 주의

**numpy 2가 필수다.** rerun-sdk 0.23은 numpy 2의 `asarray(copy=)` 시그니처를 쓴다.
numpy 1.26에서는 쿼터니언 배치가 **조용히 누락**되고 경고만 남아서, 회전이 빠진 채
재생본이 만들어진다(P1 실측). `nuscenes-devkit` 1.2.0은 `numpy<2.0.0`을 선언하지만
판독 경로는 numpy 2에서 정상 동작함을 변환·검증 게이트로 확인했다.

## P1 검증 결과 요약

| 항목 | 결과 |
|---|---|
| 좌표 변환 (§8) | ENU→WGS84→ENU 왕복 무손실, 10/10 장면이 지도 래스터 범위 내, 거리 오차 ≤0.014% |
| MCAP 유효성 | 3장면 × 9항목 전부 통과 — 인덱스·내장 스키마·구간 랜덤 액세스·JPEG 매직 |
| 신호 샘플링 | 19.9~20.0Hz (키프레임 2Hz가 아니라 `sample_data` 체인 전체) |
| 기하 정합 | LiDAR 사거리 101m(HDL32E 사양 부합), 미관측 객체가 더 멂(46.3m vs 37.1m) |
| Rerun 재생 | 엔티티 23개 · 컴포넌트 175종, 회전 포함 전 계층 기록 확인 |
