# FleetSentinel — 데이터 설계 v3.0 (자율주행 멀티모달)

> **어떤 데이터가 / 어느 규모로 / 어떤 형식으로 들어오는가**를 정리한 데이터 설계 문서.
> 시스템 전체 설계는 [`sdd.md`](sdd.md) v3.0이고, 이 문서는 그중 **데이터 계약**을 상세화한다.
> 두 문서가 충돌하면 **데이터 사항은 이 문서가, 아키텍처·의사결정은 SDD가** 우선한다.
>
> **모든 수치는 실측값이다** — nuScenes mini 10장면(196.5초) 전수 측정.

| 항목 | 값 |
|---|---|
| Status | P1 검증 완료 (미해결 5건 중 3건 해소, §14) |
| 작성일 | 2026-08-22 (P1 실측 반영: 같은 날) |
| 측정 기반 | nuScenes mini 10장면 · 196.5초 · 차량 1대분 |
| 도메인 전환 | 차량 OBD fleet 텔레메트리 → **자율주행 멀티모달 센서 플랫폼** |

---

## 1. 이 문서의 목적

v2.0은 **차량 1대가 초당 1건, 11개 스칼라 필드**를 보내는 OBD 텔레메트리를 전제했다.
자율주행 데이터는 **대역폭이 3자리 다른 이종 스트림 3계층**이라 저장·수집·활용 설계가 근본적으로 달라진다.

이 문서는 세 질문에만 답한다.

1. **무엇을(What)** — 어떤 데이터가 어디서 나오는가 (§2, §3, §4)
2. **무엇을 위해(Why)** — 각 데이터가 어떤 사용처로 흘러가는가 (§5)
3. **어떻게(How)** — 어떤 프로토콜로 수집하고 어떤 포맷·계층에 저장하는가 (§6–§10)

---

## 2. 원천 데이터

### 2.1 1차 원천 — nuScenes (실측)

[nuScenes](https://www.nuscenes.org/)는 자율주행 전체 센서 스위트를 갖춘 최초의 공개 데이터셋이다.
**합성이 아니라 보스턴·싱가포르 실도로에서 수집된 실측 데이터**이며, 이 프로젝트는 이를
**원래 타임스탬프대로 재생(replay)** 해 실시간 스트림으로 흘린다.

| 항목 | 값 |
|---|---|
| 장면(scene) | 1,000개 × **각 20초** |
| 수집 지역 | boston-seaport, singapore-onenorth, singapore-queenstown, singapore-hollandvillage |
| 카메라 | **6대** (CAM_FRONT / FRONT_LEFT / FRONT_RIGHT / BACK / BACK_LEFT / BACK_RIGHT) @ 12Hz |
| LiDAR | 1대 (Velodyne HDL32E, 32빔) @ 20Hz |
| 레이더 | **5대** (FRONT / FRONT_LEFT / FRONT_RIGHT / BACK_LEFT / BACK_RIGHT) @ 13Hz |
| 키프레임 | **2Hz** — 6센서 동기화 시점. 3D 라벨은 키프레임에만 존재 |
| 라벨 | 1.4M 3D 박스 / 40k 키프레임, 23개 클래스(검출 벤치마크는 10개) |
| 규모 | 카메라 1.4M장, LiDAR 390k sweep, 레이더 1.4M sweep — **전체 약 550GB** |
| mini | 10 scene, **4.17GB** — 즉시 착수용 |
| 분할 | train 700 / val 150 / test 150 |
| CAN bus 확장 | 별도 다운로드(745MB, 인증 불필요). 실측 주기는 §3.1 |

**라이선스**: 비상업 연구용(CC BY-NC-SA 4.0 계열). 포트폴리오 용도는 허용 범위이나
**재배포 금지** — 레포에 데이터 파일을 커밋하지 않는다(§12).

### 2.2 2차 원천 — CARLA + OpenSCENARIO (Phase 8, 스트레치)

**폐기가 아니라 역할 분리**다. nuScenes는 "실제로 무슨 일이 일어났는가"를 주고,
CARLA는 "**실주행에 부족한 상황을 의도적으로 만든다**". 이 둘이 합쳐져야
데이터 엔진의 폐루프(§5.3)가 완성된다.

- ASAM OpenSCENARIO는 CARLA / esmini / CarMaker 간 **시나리오 이식이 가능**한 표준이다.
- 로컬 제약: CARLA는 x86 + GPU를 요구해 Apple Silicon 로컬에서 실행이 어렵다 → GPU 환경 확보 시 착수.

### 2.3 기각한 원천

| 원천 | 기각 사유 |
|---|---|
| 기존 합성 생성기(`generator/`) | 물리 근사 합성 — "실 서비스가 아니다"라는 근본 지적을 해소하지 못함 |
| SUMO + TraCI | 교통 시뮬이라 **센서가 없다**. 위치·속도만 실측이고 `rpm`/`fuel_pct`/`coolant_temp`는 브리지가 합성 |
| Kaggle Levin OBD | 진짜 OBD 신호지만 **멀티모달 센서·인지 산출이 없어** 자율주행 도메인이 성립하지 않음 |
| comma2k19 | v2.0 §13 R-2에서 이미 기각(97GB, 인지연구용) — 유지 |

---

## 3. 데이터 3계층 — 대역폭이 설계를 결정한다

**이 표가 이 문서 전체에서 가장 중요하다.** 대역폭은 99배 차이인데 **메시지 건수는 오히려
신호가 9배 많다.** 이 비대칭 때문에 "모든 데이터를 하나의 Kafka 레코드로"라는 v2.0 모델이
여기서 성립하지 않는다.

| 계층 | 내용 | 주기(실측) | **메시지/초** | **대역폭** | 전송 경로 |
|---|---|---|---|---|---|
| **① 신호(Signal)** | CAN 버스, IMU, 조향, 차량 자세 | 2–955Hz | **1,295** | **432 KB/s** | 경량 → Kafka |
| **② 인지 산출(Perception)** | 3D 박스, 트랙 ID, 클래스, 가시성 | 2.06Hz(키프레임) | 2.1 | 39 KB/s | 경량 → Kafka |
| **③ 원시 센서(Raw)** | 카메라 6대, LiDAR 1대, 레이더 5대 | 11.8–20Hz | 158.8 | **27.15 MB/s** | **중량 → 오브젝트 스토리지** |

| 비교 | 중량 ÷ 경량 |
|---|---|
| 대역폭 | **58배** |
| 메시지 건수 | 0.12배 (경량이 8배 많음) |

> **신호 발생률 정정.** 초안은 1,466 rec/s로 적었는데, `ego_pose`를 **전 채널의
> sample_data마다**(158.8Hz) 센 값이었다. 실제 구현은 LIDAR 체인 한 줄(19.5Hz)을 쓰므로
> **1,295 rec/s**가 맞다. `ego_pose`를 158.8Hz로 올리면 1,434 rec/s가 되지만, 같은 순간의
> 자세를 센서 수만큼 중복 기록하는 셈이라 채택하지 않았다.

차량 500대면 원시 **13.6 GB/s** — Kafka에 태울 수 있는 양이 아니다. 반면 경량은 137 MB/s로 여유롭다.

### 3.1 채널별 실측 — 몇 Hz로, 어떤 크기로, 어떤 형식으로

#### ③ 원시 센서 (12채널)

| 채널 | 형식 | Hz | 평균 크기 | 대역폭 |
|---|---|---|---|---|
| `LIDAR_TOP` | `.pcd.bin` — float32 ×5 (x, y, z, intensity, ring) | 20.0 | **678.1 KB** | **13.90 MB/s** |
| `CAM_FRONT_RIGHT` | JPEG 1600×900 | 11.9 | 183.2 KB | 2.23 MB/s |
| `CAM_FRONT_LEFT` | JPEG 1600×900 | 11.9 | 177.7 KB | 2.17 MB/s |
| `CAM_FRONT` | JPEG 1600×900 | 11.9 | 176.5 KB | 2.15 MB/s |
| `CAM_BACK_RIGHT` | JPEG 1600×900 | 11.9 | 180.0 KB | 2.20 MB/s |
| `CAM_BACK_LEFT` | JPEG 1600×900 | 11.8 | 170.8 KB | 2.07 MB/s |
| `CAM_BACK` | JPEG 1600×900 | 11.8 | 157.8 KB | 1.90 MB/s |
| `RADAR_FRONT` | `.pcd` (텍스트 헤더 + 바이너리) | 13.4 | 9.1 KB | 0.12 MB/s |
| `RADAR_BACK_RIGHT` | `.pcd` | 13.4 | 8.6 KB | 0.12 MB/s |
| `RADAR_BACK_LEFT` | `.pcd` | 13.4 | 8.4 KB | 0.12 MB/s |
| `RADAR_FRONT_RIGHT` | `.pcd` | 13.6 | 6.3 KB | 0.09 MB/s |
| `RADAR_FRONT_LEFT` | `.pcd` | 13.7 | 5.4 KB | 0.08 MB/s |
| **합계** | | **158.8** | | **27.15 MB/s** |

**LiDAR 한 채널이 카메라 6대 합(12.7 MB/s)보다 크다.** 압축 없는 점군이기 때문이다.

#### ① 신호 (CAN + ego_pose) — 채널 네이티브 주기

3장면 60초를 실제로 추출해 측정한 값이다(신호 77,714건).

| 채널 | 형식 | Hz | 필드 |
|---|---|---|---|
| **`zoesensors`** | JSON | **937.4** | `brake_sensor`, `steering_sensor`, `throttle_sensor` |
| `ms_imu` | JSON | 97.0 | `linear_accel`, `q`, `rotation_rate` |
| `zoe_veh_info` | JSON | 96.9 | 차량 정보 8종 |
| `steeranglefeedback` | JSON | 94.2 | `value` (rad) |
| `pose` | JSON | 48.3 | `pos`, `vel`, `accel`, `orientation`, `rotation_rate` |
| `ego_pose` | JSON | 19.5 | `translation`, `rotation`(쿼터니언), 파생 `lat`/`lon` |
| `vehicle_monitor` | JSON | 2.0 | `vehicle_speed`, `yaw_rate`, `steering`, `brake`, `throttle`, `gear_position`, `rear_left_rpm`, `rear_right_rpm`, `battery_level`, 방향지시등 |
| **합계** | | **1,295.2 rec/s** | 평균 레코드 342 B |

> ⚠️ **`zoesensors`가 937Hz다.** 샘플 간격이 **0.25ms**까지 내려간다 — 페달·조향 원시
> 센서를 밀리초 이하로 뽑는다. 이 한 채널이 신호 레코드의 **72%** 를 차지한다.
> 설계 초안은 `ms_imu` 100Hz가 최고인 줄 알았으나 실제로는 9배 높은 채널이 있었다.
>
> **다운샘플하지 않는다.** `ego_pose` 시각(20Hz)에 최근접 결합하면 이 채널의 98%가
> 버려진다. 신호 계층에도 무손실 원칙을 적용하고, 메시지 수는 배치로 흡수한다.

##### 전송 배치는 이 문서 범위 밖이다

초당 1,295 레코드를 어떻게 묶어 보낼지는 **전송 설계**이고 데이터 정의가 아니다.
측정 과정에서 창 크기별 수치가 먼저 나왔으므로
[`pipeline-notes-provisional.md`](pipeline-notes-provisional.md)에 잠정 기록으로 격리했다.

이 문서가 확정하는 것은 **"초당 1,295 레코드, 평균 342 B, 채널별 주기는 위 표"** 까지다.

#### ② 인지 산출

| 항목 | 실측 |
|---|---|
| 키프레임 주기 | **2.06Hz** (평균 간격 0.504초) |
| 키프레임당 객체 | 평균 **45.9개**, 최대 **156개** |
| 객체 발생률 | **94.3 객체/초** |
| 메시지 형식 | 키프레임당 1건, 객체 배열을 담음 |
| 대역폭 | 39 KB/s (객체 레코드 ~420B 기준) |

#### fleet 규모별 환산

| 차량 | Kafka msg/s (배치 전) | Kafka 대역폭 | 스토리지 | 하루 축적 |
|---|---|---|---|---|
| 1 | 1,468 | 268 KB/s | 27 MB/s | 2.3 TB |
| 10 | 14,682 | 2.7 MB/s | 272 MB/s | 23.5 TB |
| 100 | 146,816 | 27.5 MB/s | 2,715 MB/s | 235 TB |
| 500 | 734,080 | 137 MB/s | 13,575 MB/s | 1,173 TB |

**차량 1대만으로 27.15 MB/s인데 LTE 실효 대역폭은 약 12.5 MB/s다.** 한 대조차 연속
업로드가 불가능하며, 이것이 트리거 클립 방식([SDD](sdd.md) §3 S-2)이 물리적 필연인 이유다.

배치 없이 원시 레이트로 보내면 500대에서 734,080 msg/s이고 레코드가 180바이트에 불과해
브로커 오버헤드가 지배적이다. **100ms 창 배치**를 적용하면 차량당 10 msg/s(메시지당 ~147
레코드, ~27KB)로 줄어 **500대 = 5,000 msg/s**가 된다 ([SDD](sdd.md) §3 S-3).

> **설계 귀결 — Claim-Check(참조 전달) 패턴**
> ③은 오브젝트 스토리지에 직접 적재하고, 메시지 버스에는 **참조 + 메타데이터만** 흘린다.
> ①②는 기존 v2.0 파이프라인(Kafka→Flink→Iceberg/ES)을 **그대로 재사용**한다.

---

## 4. 데이터 사전 — 스키마 3종

v2.0의 단일 `telemetry-event.avsc`(OBD 11필드)를 계층별 3종으로 분리한다.
`dlq-envelope.avsc`는 **변경 없이 재사용**한다.

### 4.1 `vehicle-signal.avsc` — 신호 계층

| 필드 | 타입 | 제약 | 설명 | nuScenes 출처 |
|---|---|---|---|---|
| `event_id` | string(ULID) | PK, 멱등키 | 재생기가 1회 발급, 재시도에도 불변 | (생성) |
| `vehicle_id` | string | NOT NULL, 파티션 키 | 재생 시 배분된 가상 차량 id | (배분, §6.2) |
| `scene_id` | string | NOT NULL | 소속 장면 — 클립 카탈로그 조인 키 | `scene.token` |
| `sensor_time` | timestamp-micros | NOT NULL | **센서 자체 클럭** 시각 | `ego_pose.timestamp` |
| `log_time` | timestamp-micros | NOT NULL | 온보드 기록 시각 | (재생 시 부여) |
| `pos_x`/`pos_y`/`pos_z` | double | NOT NULL | ENU 지역 지도 좌표(m). **WGS84 아님** — §8 | `ego_pose.translation` |
| `quat_w/x/y/z` | double | NOT NULL | 자세 쿼터니언 | `ego_pose.rotation` |
| `lat`/`lon` | double | 파생, nullable | ENU→WGS84 변환 결과(§8). 변환 실패 시 null | (파생) |
| `speed_mps` | double | >= 0 | 속도 | CAN `vehicle_monitor` |
| `accel_x/y/z` | double | | ego frame 가속도(m/s²) | CAN `pose` |
| `steering_rad` | double | **[-7.7, 6.3]** | 조향각(rad). 0=직진, 양수=좌회전, 음수=우회전 | CAN `steeranglefeedback` |
| `yaw_rate` | double | | IMU 각속도 z축(rad/s) | CAN `ms_imu` |
| `location` | string | NOT NULL | boston-seaport 등 4종 | `log.location` |

> `steering_rad` 범위 [-7.7, 6.3]은 nuScenes CAN bus 문서가 명시한 실제 관측 범위다.
> **비대칭이며 ±π를 넘는다** — 조향 휠 회전각이지 바퀴 각도가 아니기 때문. 검증 규칙에 그대로 반영한다.

### 4.2 `perception-object.avsc` — 인지 산출 계층

| 필드 | 타입 | 제약 | 설명 | nuScenes 출처 |
|---|---|---|---|---|
| `event_id` | string(ULID) | PK, 멱등키 | | (생성) |
| `scene_id` / `sample_id` | string | NOT NULL | 장면 / 키프레임 식별자 | `scene.token` / `sample.token` |
| `vehicle_id` | string | NOT NULL | 관측한 ego 차량 | (배분) |
| `sensor_time` | timestamp-micros | NOT NULL | 키프레임 시각 | `sample.timestamp` |
| `track_id` | string | NOT NULL | **동일 객체의 시간축 연속 식별자** | `instance.token` |
| `category` | string | NOT NULL | car, truck, bus, pedestrian, bicycle, motorcycle, … (23종) | `category.name` |
| `attribute` | string | nullable | vehicle.moving / vehicle.parked / pedestrian.moving 등 | `attribute.name` |
| `center_x/y/z` | double | NOT NULL | 박스 중심(글로벌 프레임, m) | `sample_annotation.translation` |
| `size_w/l/h` | double | > 0 | 박스 크기(m) | `sample_annotation.size` |
| `rot_w/x/y/z` | double | NOT NULL | 박스 자세 쿼터니언 | `sample_annotation.rotation` |
| `vel_x/y` | double | nullable | 객체 속도(m/s) | (devkit 산출) |
| `visibility` | string | NOT NULL | `v0-40` / `v40-60` / `v60-80` / `v80-100` | `visibility.level` |
| `num_lidar_pts` | int | >= 0 | 박스 내 LiDAR 포인트 수 — **라벨 신뢰도 프록시** | `sample_annotation` |
| `num_radar_pts` | int | >= 0 | 박스 내 레이더 포인트 수 | `sample_annotation` |

> `num_lidar_pts`가 중요하다. **0이면 실질적으로 관측되지 않은 객체**라 학습셋에서 제외하거나
> 별도 취급해야 한다 — §11 품질 규칙의 근거가 된다.

### 4.3 `log-segment.avsc` — Claim-Check 참조 계층

**이 스키마가 v3.0의 핵심 신규 요소다.** 중량 데이터를 버스에 태우지 않고 참조만 흘린다.

| 필드 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `segment_id` | string(ULID) | PK | 세그먼트 식별자 |
| `scene_id` | string | NOT NULL | 장면 식별자 |
| `vehicle_id` | string | NOT NULL | 배분된 가상 차량 |
| `blob_uri` | string | NOT NULL | **MCAP 파일 위치** (s3://… / gs://…) |
| `t_start` / `t_end` | timestamp-micros | NOT NULL | 세그먼트 시간 범위 |
| `sensor_channels` | array\<string\> | NOT NULL | 포함된 채널 목록(CAM_FRONT, LIDAR_TOP, …) |
| `size_bytes` | long | > 0 | 세그먼트 크기 |
| `checksum` | string | NOT NULL | 무결성 검증(sha256) |
| `sample_count` | int | > 0 | 포함 샘플 수 |
| `mcap_schema_version` | string | NOT NULL | MCAP 내장 스키마 버전 |
| `calibration` | map | NOT NULL | **채널별 센서 외부/내부 파라미터.** 없으면 MCAP만으로 3D 재생 불가 — P1에서 발견해 추가(§14.3) |

---

## 5. 사용처 — "무엇을 위해 쓰는가"

### 5.1 데이터 → 사용처 매트릭스

| 데이터 | 실시간 관제 | ML 데이터엔진 | 데이터 품질 | 저장 계층 |
|---|---|---|---|---|
| 신호: ego pose, lat/lon | ✅ 지도 위 fleet 위치·궤적 | ➖ | ✅ 타임스탬프 역전 검출 | Iceberg + ES |
| 신호: 속도·가속도 | ✅ 급제동 이벤트 알림 | ✅ 거동 조건 태그 | ✅ 물리 범위 검증 | Iceberg + ES |
| 신호: 조향각·yaw rate | ✅ 시계열 플롯 | ✅ **좌/우회전 시나리오 태그** | ✅ 범위 검증 | Iceberg |
| 인지: 3D 박스·클래스 | ✅ 프레임당 객체 수·클래스 분포 | ✅ **학습셋 본체** | ✅ `num_lidar_pts=0` 검출 | Iceberg |
| 인지: track_id | ✅ 트랙 수 추이 | ✅ **컷인·추월 등 상호작용 마이닝** | ✅ 트랙 단절 검출 | Iceberg |
| 인지: visibility | ➖ | ✅ 난이도 계층화 | ✅ 라벨 신뢰도 | Iceberg |
| 원시: 카메라·LiDAR·레이더 | ✅ **Rerun 센서 재생** | ✅ 학습 입력 | ✅ 센서 드롭아웃 검출 | 오브젝트 스토리지(MCAP) |
| log-segment 메타 | ✅ 클립 재생 진입점 | ✅ 클립 검색 결과 | ✅ 체크섬 무결성 | Iceberg (카탈로그) |

### 5.2 관제(Monitoring)에서 쓰는 법

| 화면 | 사용 데이터 | 도구 |
|---|---|---|
| fleet 지도 — 다수 차량 위치·궤적 | 신호(lat/lon, speed) | **Kibana Maps** (v2.0 자산 재사용) |
| 센서 재생 — 6카메라+포인트클라우드+3D박스 | 원시(MCAP) + 인지 | **Rerun** |
| 신호 시계열 — 속도·조향·가속도 | 신호 | Kibana / Grafana |
| 인지 지표 — 프레임당 객체 수·클래스 분포 | 인지 | Kibana |
| 이벤트 알림 — 급제동·센서 드롭아웃 | 신호 + log-segment | Kibana Alerting |
| 파이프라인 건강 — Kafka lag·체크포인트·DLQ | 운영 메트릭 | Prometheus/Grafana (v2.0 §10.2) |

> **정직한 프레이밍**: nuScenes 재생은 라이브 차량 관제가 아니다. 다만 재생을 실시간 스트림으로
> 흘리면 관제 시스템이 풀어야 할 기술 요구(순서·지연·유실·동기화·백프레셔)는 동일하게 발생한다.
> "실측 로그 기반 관제 플랫폼"으로 기술한다.

### 5.3 ML 데이터엔진에서 쓰는 법 — 폐루프

**여기가 이 프로젝트의 핵심 서사다.** 모델을 학습시키는 게 아니라
**모델을 학습시킬 수 있는 데이터를 만드는 시스템**을 짓는다.

```
① 시나리오 마이닝     인지+신호 Iceberg에 조건 쿼리
   "야간 + 우천 + 좌회전 중 보행자 컷인"  →  해당 클립 목록
                │
                ▼
② 커버리지 분석       조건별 클립 수 히트맵 → 부족 구간 식별
                │
                ├──────────────▶ ④ CARLA/OpenSCENARIO로 부족분 생성 (Phase 8)
                │                    └─ 생성 결과가 다시 ①로 유입
                ▼
③ 학습셋 스냅샷       선정 클립 집합을 Iceberg 스냅샷으로 고정
                       → time travel로 "v3 모델 = 정확히 이 데이터" 재현 보장
```

| 기능 | 필요 데이터 | 구현 근거 |
|---|---|---|
| 시나리오 마이닝 | 인지(클래스·track_id·visibility) + 신호(조향·속도) + 조건태그 | Iceberg 파티션 프루닝 + 클립 카탈로그(§10) |
| **학습셋 버저닝** | 클립 카탈로그 스냅샷 | **Iceberg time travel** — v2.0에서 근거로만 적었던 기능이 여기서 실사용된다 |
| 오토라벨링 대상 선정 | `num_lidar_pts`, `visibility` | 저신뢰 라벨 우선 재처리 |
| 커버리지 히트맵 | 조건태그 × 클립 수 | Gold 집계 |
| 평가 회귀 세트 | 클립 카탈로그 + OpenSCENARIO 시나리오 | Phase 8 |

---

## 6. 수집 경로와 프로토콜

### 6.1 프로토콜 계층 분리

**"MQTT냐 gRPC냐"가 아니라 계층마다 다른 것을 쓴다.** 각 선택의 근거:

| 프로토콜 | 담당 구간 | 채택 근거 |
|---|---|---|
| **MQTT** | 신호 업링크 (차량→클라우드) | 셀룰러 단절 전제 설계. QoS1 재전송, **LWT로 차량 오프라인 즉시 검출**, 헤더 오버헤드 최소 |
| **gRPC** | 인지 산출 스트림 + 명령/제어 | protobuf 스키마 강제, 양방향 스트리밍, HTTP/2 멀티플렉싱. 양 끝단 통제 시 최적 |
| **HTTPS resumable** | 원시 센서 벌크 업로드 | 대용량 + 끊김 복구. 오브젝트 스토리지 표준 경로 |
| **WebSocket** | 관제 대시보드 → 브라우저 | 프론트엔드 푸시. **차량 업링크 아님** |
| RTSP / WebRTC | (스코프 밖) 원격 teleop 라이브 뷰 | 기록용이 아니라 실시간 감시 전용 |
| ROS 2 (DDS/Zenoh) | (스코프 밖) 차량 **내부** 노드 간 | DDS는 LAN 전제. 광역은 Zenoh가 적합하나 본 프로젝트는 온보드 스택 미보유 |

### 6.2 재생기(Replayer) 설계

nuScenes는 **20초 클립 1,000개**이지 연속 주행 로그가 아니다. 그대로 재생하면 20초마다 끊긴다.

**대응 — N대 가상 차량 배분**: 1,000개 scene을 N대 가상 차량에 배분해 **동시 재생**한다.

- 지도에 수십 대가 동시에 움직이는 **fleet 관제 화면**이 성립한다
- 파이프라인에 실제 동시 부하가 걸린다 → 처리량 측정 대상이 생긴다
- 배속(`--speed`)을 올리면 그대로 부하 테스트가 된다 (v2.0 §15 LT-LOAD-01 프로토콜 재사용)

```
nuScenes mini/full
   └─ nuscenes2mcap ─▶ MCAP 파일 (scene별)
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
     경량 추출(신호·인지)        MCAP 세그먼트 업로드
     N대 배분 + 배속 제어         → MinIO(로컬) / GCS
              │                       │
        MQTT/gRPC                     │
              ▼                       ▼
           Kafka ──▶ Flink ──▶ Iceberg + ES ◀── log-segment 메타
```

`event_id`(ULID) 발급 계약은 v2.0과 동일하다 — **재생기가 1회 발급하고 재전송에도 재사용**한다.
이것이 Flink dedup / Iceberg 2PC / ES 멱등 upsert의 성립 조건이다.

---

## 7. 시간 계약 — 타임스탬프 3종

v2.0은 `event_time` + `ingest_time` 2종이었다. 멀티모달에서는 **센서마다 클럭과 주기가 다르므로**
(카메라 12Hz / LiDAR 20Hz / 레이더 13Hz / CAN pose 50Hz) 3종이 필요하다.

| 타임스탬프 | 부여 주체 | 용도 |
|---|---|---|
| `sensor_time` | 센서 자체 클럭 (nuScenes 원본) | **정본 시간축**. 파티션 기준, 센서 간 정렬 기준 |
| `log_time` | 온보드 기록 시점 (재생기 부여) | 온보드 버퍼링 지연 관측 |
| `ingest_time` | 파이프라인 수신 시점 | 전송 지연 관측 `lag = ingest_time - sensor_time` |

**동기화 기준 = 키프레임(2Hz)**. nuScenes가 6센서를 정렬하는 단위이며 3D 라벨도 여기에만 붙는다.
센서 간 조인은 키프레임을 앵커로 하고, 그 사이 고주파 신호는 키프레임 구간에 귀속시킨다.

**late 데이터 정책은 v2.0을 승계**한다 — watermark 초과를 이유로 폐기하지 않고
`sensor_time` 파티션에 그대로 적재한다(무손실 원칙 G-1).

---

## 8. 좌표계 계약 — ENU → WGS84 (⚠️ 실무 함정)

**nuScenes `ego_pose.translation`은 위경도가 아니다.** 지역 지도의 **ENU(East-North-Up) 로컬 프레임 미터 좌표**이고
`z`는 항상 0이다. Kibana Maps의 `geo_point`는 WGS84 위경도를 요구하므로 변환이 필요하다.

| 계층 | 좌표 표현 | 비고 |
|---|---|---|
| Bronze | `pos_x/y/z` (ENU, m) 원본 그대로 | 무손실 — 변환 오차를 원본에 섞지 않는다 |
| Silver | ENU 원본 **+** 파생 `lat`/`lon` | 변환 실패 시 `lat`/`lon` = null (행은 유지) |
| ES | `location` = `geo_point` | Kibana Maps 필수 |

**변환에 필요한 것**: 4개 지역(boston-seaport, singapore-*)별 **고정 기준 원점(lat/lon)**.
경로는 `WGS84 → ECEF → 로컬 ENU`의 역변환이다.

> ✅ **P1에서 해소됨(R-V3-1).** 원점은 포럼 추정이 아니라 `nuscenes-devkit`
> `map_expansion/map_api.py` 45–49행의 **공식 문서화 값**이었다. 그리고 "보스턴 1.35× 스케일링"은
> **Web Mercator 축척계수 `1/cos(42.34°) = 1.3528`** 이었다 — 로컬 접평면/대권 방식으로 직접
> 변환하면 어떤 보정 상수도 필요 없다. 왕복 무손실·지도 래스터 정합·거리 오차 ≤0.014%로 검증했다.
> 상세는 §14.1, 구현은 [`exploration/fleetsentinel_ingest/geo.py`](../exploration/fleetsentinel_ingest/geo.py).

v2.0 §6.6의 **lat/lon 순서 규약은 그대로 유지**한다 — BigQuery/GeoJSON = `[lon, lat]`, ES 문자열 = `"lat,lon"`.

---

## 9. 저장 설계 — Medallion 재정의

| 계층 | v2.0 (OBD) | **v3.0 (자율주행)** | 저장소 |
|---|---|---|---|
| **Bronze** | Kafka 원본 이벤트 append-only | ① 신호·인지 원본 append-only **+ ② MCAP 세그먼트 원본** | Iceberg + **오브젝트 스토리지** |
| **Silver** | 중복제거·검증·차량메타 조인 | 중복제거·검증·좌표 파생·키프레임 정렬 | Iceberg |
| **Gold** | 속도·급브레이크·연비 집계 | **클립 카탈로그 + 조건태그 + 커버리지 집계** | Iceberg / BigQuery |

**Bronze가 2원화되는 것이 v3.0의 구조적 변화다.** MCAP 원본은 그대로 보존해
**언제든 재생·재처리 가능**하게 두고, 그로부터 추출한 구조화 데이터만 Iceberg에 적재한다.

### 9.1 왜 MCAP인가

[MCAP](https://foxglove.dev/product/mcap)은 이종 타임스탬프 메시지를 채널별로 담는 컨테이너 포맷이다.

- **스키마 내장(self-describing)** — 파일만 있으면 장기적으로 해석 가능
- **인덱스 보유** — 랜덤 액세스로 특정 구간만 읽을 수 있다(클립 재생의 전제)
- **ROS 2 Iron부터 rosbag2 기본 포맷** — 로보틱스 생태계 표준
- Rerun / Foxglove가 네이티브로 연다

즉 **"로보틱스판 Parquet"** 역할이다. 원본 로그 보존과 재생 가능성을 동시에 만족한다.

> ✅ **스윕 누락 결함 해소(2026-08-24).** 초기 변환기는 **키프레임만** 담아 원시 센서의
> 86%가 빠져 있었다(`sample_data` 31,206건 중 4,848건, 바이트로 13.6%). 전 채널의
> `sample_data` 체인을 순회하도록 고쳤다.
>
> | 장면 | MCAP 원시 | 정본 | 판정 |
> |---|---|---|---|
> | scene-0061 | 2,963 (키프레임 468 + 스윕 2,495) | 2,963 | ✅ |
> | scene-0103 | 3,063 (480 + 2,583) | 3,063 | ✅ |
> | scene-0553 | 3,171 (492 + 2,679) | 3,171 | ✅ |
>
> 장면당 MCAP은 49MB → **357MB**로 커졌다(원본 475.8MB를 압축). 세그먼트 분할 단위는
> **클립 1개 = MCAP 1파일**로 확정했다. `verify_mcap.py`에 정본 대조 게이트를
> 상설화해 회귀를 막는다 — `verify_mcap.py <mcap_dir> <dataroot>`.

### 9.2 Silver DDL (Flink SQL / Iceberg)

```sql
-- 신호 계층
CREATE TABLE iceberg_catalog.silver.vehicle_signals (
  event_id      STRING       NOT NULL,   -- ULID, 멱등키
  vehicle_id    STRING       NOT NULL,
  scene_id      STRING       NOT NULL,
  sensor_time   TIMESTAMP(6) NOT NULL,   -- 정본 시간축, 파티션 컬럼
  log_time      TIMESTAMP(6) NOT NULL,
  ingest_time   TIMESTAMP(6) NOT NULL,
  pos_x         DOUBLE, pos_y DOUBLE, pos_z DOUBLE,   -- ENU(m) 원본
  quat_w        DOUBLE, quat_x DOUBLE, quat_y DOUBLE, quat_z DOUBLE,
  lat           DOUBLE, lon DOUBLE,                    -- 파생, 변환 실패 시 null
  speed_mps     DOUBLE,
  accel_x       DOUBLE, accel_y DOUBLE, accel_z DOUBLE,
  steering_rad  DOUBLE,
  yaw_rate      DOUBLE,
  location      STRING       NOT NULL,
  PRIMARY KEY (event_id) NOT ENFORCED
) PARTITIONED BY (days(sensor_time))
WITH ('format-version' = '2', 'write.upsert.enabled' = 'true');

-- 인지 산출 계층
CREATE TABLE iceberg_catalog.silver.perception_objects (
  event_id      STRING       NOT NULL,
  scene_id      STRING       NOT NULL,
  sample_id     STRING       NOT NULL,
  vehicle_id    STRING       NOT NULL,
  sensor_time   TIMESTAMP(6) NOT NULL,
  track_id      STRING       NOT NULL,
  category      STRING       NOT NULL,
  attribute     STRING,
  center_x      DOUBLE, center_y DOUBLE, center_z DOUBLE,
  size_w        DOUBLE, size_l DOUBLE, size_h DOUBLE,
  rot_w         DOUBLE, rot_x DOUBLE, rot_y DOUBLE, rot_z DOUBLE,
  vel_x         DOUBLE, vel_y DOUBLE,
  visibility    STRING       NOT NULL,
  num_lidar_pts INT          NOT NULL,
  num_radar_pts INT          NOT NULL,
  PRIMARY KEY (event_id) NOT ENFORCED
) PARTITIONED BY (days(sensor_time))
WITH ('format-version' = '2', 'write.upsert.enabled' = 'true');
```

파티션은 v2.0과 동일하게 `days(sensor_time)` **hidden partitioning**을 쓴다.
`vehicle_id` 버킷 파티션은 v2.0과 같은 이유로 기각한다(small-file 폭증).

### 9.3 Elasticsearch 인덱스 (관제 서빙)

v2.0의 `telemetry-fleet` 단일 인덱스 + `doc_id=event_id` 멱등 upsert 구조를 **그대로 승계**하고
필드만 교체한다(data stream 미사용 근거도 동일 — upsert 불가).

```json
{
  "index_patterns": ["av-signals"],
  "template": { "mappings": { "properties": {
    "event_id":     { "type": "keyword" },
    "vehicle_id":   { "type": "keyword" },
    "scene_id":     { "type": "keyword" },
    "sensor_time":  { "type": "date" },
    "location_geo": { "type": "geo_point" },
    "speed_mps":    { "type": "float" },
    "steering_rad": { "type": "float" },
    "yaw_rate":     { "type": "float" },
    "location":     { "type": "keyword" }
  }}}
}
```

---

## 10. 클립 카탈로그 — 두 경로가 만나는 지점

경량 경로(신호·인지)와 중량 경로(MCAP)를 **조인해 검색 가능한 단위**로 만드는 테이블이다.
관제의 "재생 진입점"이자 데이터엔진의 "검색 대상"이다.

```sql
CREATE TABLE iceberg_catalog.gold.clip_catalog (
  clip_id          STRING       NOT NULL,
  scene_id         STRING       NOT NULL,
  vehicle_id       STRING       NOT NULL,
  t_start          TIMESTAMP(6) NOT NULL,
  t_end            TIMESTAMP(6) NOT NULL,
  blob_uri         STRING       NOT NULL,   -- MCAP 위치 (Claim-Check)
  location         STRING       NOT NULL,
  -- 조건 태그 (시나리오 마이닝 술어)
  time_of_day      STRING,                  -- day | night
  weather          STRING,                  -- clear | rain
  -- 인지 요약
  n_objects        INT, n_pedestrians INT, n_vehicles INT,
  max_speed_mps    DOUBLE,
  min_accel_mps2   DOUBLE,                  -- 급제동 강도
  max_abs_steering DOUBLE,                  -- 회전 강도
  has_harsh_brake  BOOLEAN,
  -- 품질 플래그
  n_zero_lidar_pts INT,                     -- 미관측 라벨 수
  sensor_dropout   BOOLEAN,
  PRIMARY KEY (clip_id) NOT ENFORCED
) PARTITIONED BY (days(t_start), location);
```

**`time_of_day`/`weather`는 nuScenes `scene.description` 자유 텍스트에서 파싱**한다
("Night", "Rain" 등이 기재됨). 파싱 규칙과 커버리지는 구현 시 실측 확인이 필요하다(미해결 §13).

시나리오 마이닝 쿼리 예:

```sql
-- "야간 + 우천 + 급제동 + 보행자 존재" 클립
SELECT clip_id, scene_id, blob_uri, t_start, n_pedestrians
FROM gold.clip_catalog
WHERE time_of_day = 'night' AND weather = 'rain'
  AND has_harsh_brake AND n_pedestrians > 0
ORDER BY min_accel_mps2 ASC;
```

---

## 11. 데이터 품질 규칙

v2.0의 DLQ 4분류(`PARSE_FAILURE` / `SCHEMA_VALIDATION_FAILURE` / `BUSINESS_RULE_FAILURE` / `SINK_WRITE_FAILURE`)를
**그대로 승계**하고 규칙만 교체한다.

| 규칙 | 대상 | 위반 시 |
|---|---|---|
| `steering_rad` ∈ [-7.7, 6.3] | 신호 | `BUSINESS_RULE_FAILURE` → DLQ |
| `speed_mps` >= 0 | 신호 | `BUSINESS_RULE_FAILURE` → DLQ |
| 쿼터니언 정규화 \|q\| ≈ 1 | 신호·인지 | `BUSINESS_RULE_FAILURE` → DLQ |
| `size_w/l/h` > 0 | 인지 | `BUSINESS_RULE_FAILURE` → DLQ |
| **`sensor_time` 단조성** (차량별 역전 금지) | 신호 | 경고 태그(폐기 안 함 — 무손실) |
| **`num_lidar_pts` = 0** | 인지 | 행 유지 + `low_confidence` 플래그 → 학습셋 제외 대상 |
| **센서 드롭아웃** (키프레임에 6센서 미충족) | log-segment | 클립에 `sensor_dropout` 플래그 |
| MCAP `checksum` 불일치 | log-segment | `SINK_WRITE_FAILURE` → 재업로드 |

**유실 0 대사(TC-RECON-01)는 v3.0에서도 유지**한다 — `scripts/recon.py`의 `event_id` 집합 교집합
방식을 신호·인지 두 스트림에 각각 적용한다.

---

## 12. 보존 / 수명주기

| 대상 | 정책 | 근거 |
|---|---|---|
| Bronze MCAP 원본 | **삭제 없음** (로컬 MinIO / 클라우드 Coldline 이관) | 재생·재처리의 전제. 손실 시 복구 불가 |
| Bronze/Silver Iceberg | 행 삭제 없음 + `expire_snapshots`(7–30일) + `remove_orphan_files` | v2.0 §6.3 승계 |
| ES `av-signals` | 30일 delete-by-query | 서빙 사본 — 정본은 Iceberg |
| 클립 카탈로그 | 삭제 없음 | 학습셋 버저닝의 정본 |
| **nuScenes 원본 데이터셋** | **레포에 커밋 금지** | 비상업 라이선스, 재배포 금지. `.gitignore` 등록 필요 |

---

## 13. v2.0 대비 변경점

### 폐기
- `schemas/telemetry-event.avsc` — OBD 11필드
- `rpm` / `fuel_pct` / `coolant_temp` — **SUMO 브리지가 합성하던 가짜 필드**. 전 필드 실측으로 대체
- Gold 5종 집계(`agg_speed_minute`, `agg_harsh_events`, `agg_fuel_efficiency`, `agg_overheat`, `agg_geofence_dwell`)
- `generator/` 합성 생성기 (→ nuScenes 재생기로 대체)
- SUMO/TraCI 브리지 (`infra/sumo/`)

### 그대로 유지 (검증된 자산)
- Kafka 3-broker KRaft HA (RF=3 / ISR=2), broker-kill 데모
- Flink exactly-once — 체크포인트 + Kafka 오프셋 2PC + `keyBy(event_id)` dedup(TTL 30m)
- Iceberg 2PC 원자 커밋, hidden partitioning, format-version 2 upsert
- ES `doc_id=event_id` 멱등 upsert, 단일 인덱스(data stream 미사용)
- DLQ 4분류 + `dlq-envelope.avsc`
- `scripts/recon.py` 유실 0 대사, `scripts/e2e.sh` E2E 하네스
- `event_id` = ULID 1회 발급 계약
- late 데이터 무기한 수용 원칙

### 신규
- 스키마 3종 (`vehicle-signal` / `perception-object` / `log-segment`)
- **Claim-Check 경로** — 오브젝트 스토리지 + 참조 메타
- **MCAP** 포맷 도입 (Bronze 2원화)
- 타임스탬프 3종 + 키프레임 동기화 계약
- **ENU → WGS84 좌표 변환**
- **클립 카탈로그** + 시나리오 마이닝
- **학습셋 스냅샷** (Iceberg time travel 실사용)
- **Rerun** 시각화 (Foxglove OSS 중단 대응)
- 프로토콜 계층 분리 (MQTT / gRPC / HTTPS / WebSocket)

---

## 14. 미해결 항목 — P1 실측 검증 결과 (2026-08-22)

nuScenes mini(4.17GB) + CAN bus 확장(745MB)을 실제로 받아 검증했다. 산출물·절차는
[`exploration/README.md`](../exploration/README.md).

| ID | 항목 | 판정 | 근거 |
|---|---|---|---|
| **R-V3-1** | ENU→WGS84 원점값, 보스턴 1.35× 스케일링 | ✅ **해소** | 아래 §14.1 |
| **R-V3-2** | `scene.description` 파싱 커버리지 | ⚠️ **부분 해소** | 아래 §14.2 |
| **R-V3-3** | CAN bus 확장 가용성 | ✅ **해소** | 아래 §14.3 |
| R-V3-4 | 원시 MCAP 보존 시 디스크 압박 | 📌 **정량화됨** | 키프레임만 담은 현재 기준 장면당 ~49MB. **스윕 포함 시 ~360MB**(§9.1 결함) → full 1000장면 ~360GB |
| R-V3-5 | 재생 배분 `vehicle_id`가 실차량 아님 | 📌 **문서화로 확정** | `AV-000N` 접두어 + 스키마 doc에 "재생 배분 가상 차량" 명시 |
| ~~R-V3-6~~ | ~~MCAP 스윕 누락~~ | ✅ **해소** | §9.1. 정본 대조 3/3 누락 0, 상설 게이트 추가 |

### 14.1 R-V3-1 — "보스턴 1.35×"의 정체는 Web Mercator 축척계수였다

원점은 포럼 추정이 아니라 **공식 문서화 값**이었다 — `nuscenes-devkit`
`map_expansion/map_api.py` 45–49행에 4개 지도의 남서쪽 모서리 좌표가 기재돼 있다.

수수께끼였던 1.35배는 **Web Mercator(EPSG:3857) 축척계수 `1/cos(lat)`** 이다.

| 지역 | 원점 위도 | `1/cos(lat)` |
|---|---|---|
| boston-seaport | 42.3368° | **1.3528** ← 포럼 보고 "1.35" |
| singapore 3곳 | ~1.29° | 1.0003 (사실상 1) |

싱가포르는 적도 근처라 보정이 필요 없었고 보스턴만 필요했던 것이다. **로컬 접평면 또는
대권 방식으로 직접 변환하면 이 보정 자체가 불필요하다.** 구현은
[`exploration/fleetsentinel_ingest/geo.py`](../exploration/fleetsentinel_ingest/geo.py).

검증 3종 통과:

1. **왕복 무손실** — ENU→WGS84→ENU 최대 오차 1e-6 mm
2. **지도 래스터 대조** — 10/10 장면의 `ego_pose`가 지도 PNG 범위(10px/m) 안. 원점·스케일 정합 확인
3. **거리 보존** — haversine 대 ENU 거리 오차 ≤ 0.014%

추가로 `nuscenes2mcap`의 대권 방식 구현과 교차 대조해 **최대 편차 36cm**(싱가포르 2cm)로
일치했다. 두 독립 구현이 서브미터로 수렴하므로 원점·방법 모두 타당하다.

### 14.2 R-V3-2 — 태그는 100% 뽑히지만 `time_of_day`·`weather`는 약하다

mini 10장면 전부에서 태그가 1개 이상 추출됐다. 그러나 설계가 전제한 두 축은 약하다.

| 태그 | 10장면 중 | 비고 |
|---|---|---|
| peds | 8 | 강함 |
| cyclist / intersection / bus | 5 | 강함 |
| truck | 4 | 쓸만함 |
| night / construction / parked | 3 | 쓸만함 |
| turn / rain / hard_light | 1 | **희소** |

**두 가지 함정을 확정한다.**

- **`day`는 명시되지 않는다.** "Night"은 3건 기재되지만 "day/daytime"은 **0건**이다.
  즉 주간은 *"night이 없으므로 day"* 라는 **부정 추론**이며, 카탈로그에 그렇게 기록해야 한다.
- **`after rain` ≠ 활성 강우.** scene-1094는 "Night, after rain"으로, 노면은 젖었지만
  비는 오지 않는다. 하나로 뭉치면 안 되고 정규식도 **부정 후방탐색**이 필요하다
  (`(?<!after\s)rain` — 전방탐색으로 짜면 "after rain"을 활성 강우로 오분류한다. P1에서 실제로 겪음).

**귀결**: `weather` 축은 mini 규모에서 사실상 쓸 수 없다(활성 강우 1/10). 시나리오 마이닝의
기상 축은 ① full 데이터셋에서 재측정하거나 ② CARLA 보강 생성(Phase 8)으로 채워야 한다.
**§5.3 폐루프의 "부족분을 시뮬로 보강"이 가설이 아니라 실측으로 확인된 필요가 됐다.**

### 14.3 R-V3-3 — CAN은 mini에 없지만 공개 다운로드로 확보된다

mini 아카이브에 `can_bus/`는 **없다**. 다만 별도 확장이 **인증 없이 745MB로 공개**돼 있어
받으면 신호 계층이 온전해진다.

아래는 **scene-0061 단일 장면** 기준이다 (10장면 평균과 전 채널 목록은 §3.1 참고 — `zoesensors`
955Hz가 최고 주기 채널이며, 아래 표에는 없다):

| 채널 | 주기 | 필드 |
|---|---|---|
| `ms_imu` | 99.2Hz | `linear_accel`, `q`, `rotation_rate` |
| `steeranglefeedback` | 93.9Hz | `value` (rad) |
| `pose` | 49.0Hz | `pos`, `vel`, `accel`, `orientation`, `rotation_rate` |
| `vehicle_monitor` | 2.0Hz | `vehicle_speed`, `yaw_rate`, `steering`, `brake`, `throttle`, `gear_position`, `rear_left_rpm`, `rear_right_rpm`, `battery_level`, 방향지시등 |

§4.1의 `steering_rad` 범위 **[-7.7, 6.3]은 전체 데이터셋 기준**이다(scene-0061 실측은
[0.030, 3.065]). 검증 규칙은 전역 범위를 쓴다.

**설계 수정 1건** — §4.1은 신호를 `ego_pose` 기준으로 적었으나, 키프레임만 쓰면 **2Hz**로
너무 성기다. `sample_data` 체인 전체를 훑어 **실측 19.9~20.0Hz**로 올렸다.

**설계 누락 1건 발견 — 센서 캘리브레이션.** §4.3 `log-segment`에 캘리브레이션이 없었는데,
이게 없으면 **MCAP만으로 3D 재생이 불가능**하다(LiDAR는 센서 프레임, 인지 박스는 글로벌
프레임이라 정렬되지 않는다). `/tf/calibration` 채널을 추가해 MCAP을 자체충족적으로 만들었다.

### 14.4 P1 실측으로 확정된 수치

| 항목 | 설계 문서 | P1 실측 |
|---|---|---|
| 장면 길이 | 20초 | 19.1~20.0초 ✅ |
| 키프레임 | 2Hz | 1.98Hz ✅ |
| 센서 | 카메라6+LiDAR1+레이더5 | 12채널 확인 ✅ |
| visibility | 4단계 | `v0-40`/`v40-60`/`v60-80`/`v80-100` ✅ |
| 라이선스 | 비상업 | Motional 비상업 약관 확인 ✅ |
| **`num_lidar_pts`=0 비율** | (미상) | **23.1%** (18,538건 중 4,278건) |

마지막 항목이 §11 품질 규칙의 무게를 바꾼다. **라벨의 약 1/4이 LiDAR 관측 0**이므로,
`low_confidence` 플래그는 예외 처리가 아니라 **주요 큐레이션 축**이다.

기하 정합도 교차 확인됐다 — LiDAR 사거리 101.1m(HDL32E 사양 부합), `num_lidar_pts`=0
객체의 평균 거리가 관측된 객체보다 멀다(46.3m 대 37.1m). 좌표 처리가 물리적으로 일관된다.

### 14.5 좌표 체인 종단 검증 — 박스가 LiDAR 포인트를 감싸는가

기하 정합의 결정적 근거. 3D 박스 안에 들어오는 LiDAR 포인트를 직접 세어 nuScenes가
라벨에 기록한 `num_lidar_pts`와 대조했다.

| `half_sizes` 축 순서 | 객체 | 총 오차 |
|---|---|---|
| **`(l/2, w/2, h/2)`** | 76건 | **0 / 31,911 = 0.0%** |
| `(w/2, l/2, h/2)` | 76건 | 18,508 / 31,911 = 58.0% |

**31,911개 포인트에 대해 오차 0** — 근사가 아니라 정확한 일치다. 이 수치가 맞으려면
`LiDAR 센서 프레임 → 캘리브레이션 외부파라미터 → ego 자세 → 글로벌 프레임 → 박스 로컬 프레임`
다섯 단계가 전부 정확해야 한다. 한 링크만 틀려도 일치하지 않는다. 즉 구현이 nuScenes 자체
라벨링 파이프라인을 재현한다.

부수적으로 축 순서도 확정됐다 — `sample_annotation.size = (width, length, height)`.
`vehicle.car` 348건 중앙값이 폭 1.94m / 길이 4.70m / 높이 1.65m로 실제 승용차 치수와 맞는다.
박스 로컬 프레임의 x축은 **길이 방향**이므로 `half_sizes`는 `(l/2, w/2, h/2)` 순서다.

> 이 검증이 있어서 **재생 화면의 육안 확인은 정합성 근거로 필요하지 않다.** 눈으로만 판단
> 가능한 항목은 카메라 이미지의 3D 투영 각도뿐이며, 이는 시각화 표현이지 데이터 정합이
> 아니다(MCAP에는 캘리브레이션이 원본 그대로 보존된다).



## 15. 참고 자료

- [nuScenes: A multimodal dataset for autonomous driving (arXiv:1903.11027)](https://arxiv.org/abs/1903.11027)
- [nuScenes 공식 사이트](https://www.nuscenes.org/) · [nuscenes-devkit](https://github.com/nutonomy/nuscenes-devkit)
- [nuScenes 스키마 정의](https://github.com/nutonomy/nuscenes-devkit/blob/master/docs/schema_nuscenes.md)
- [nuScenes CAN bus 확장](https://github.com/nutonomy/nuscenes-devkit/blob/master/python-sdk/nuscenes/can_bus/README.md)
- [nuScenes 포럼 — Lon/Lat of origin points](https://forum.nuscenes.org/t/lon-lat-of-origin-points/163)
- [foxglove/nuscenes2mcap — 공식 변환기](https://github.com/foxglove/nuscenes2mcap)
- [MCAP 포맷](https://foxglove.dev/product/mcap) · [MCAP as the ROS 2 Default Bag Format](https://foxglove.dev/blog/mcap-as-the-ros2-default-bag-format)
- [Rerun (MIT/Apache-2.0)](https://github.com/rerun-io/rerun) · [Rerun nuScenes 예제](https://rerun.io/examples/robotics/nuscenes_dataset)
- [Apache Iceberg — Partitioning](https://iceberg.apache.org/docs/latest/partitioning/) · [Flink Connector](https://iceberg.apache.org/docs/latest/flink-connector/)
- [nuScenes 스키마 정의(devkit)](https://github.com/nutonomy/nuscenes-devkit/blob/master/docs/schema_nuscenes.md) · [map_api.py 원점 좌표](https://github.com/nutonomy/nuscenes-devkit/blob/master/python-sdk/nuscenes/map_expansion/map_api.py)
- [CARLA ROS Scenario Runner](https://carla.readthedocs.io/projects/ros-bridge/en/stable/carla_ros_scenario_runner/)
