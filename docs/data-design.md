# FleetSentinel — 데이터 설계 (정본)

> ## 이 문서의 역할
>
> **데이터에 관한 모든 사실은 여기에만 적는다.** 수치·필드·제약을 다른 문서가 다시 쓰지
> 않고 이 문서를 링크한다. 같은 사실이 두 곳에 있으면 반드시 어긋나기 때문이다.
>
> 답하는 질문은 셋이다 — **어떤 데이터가 / 어느 규모로 / 어떤 형식으로** 들어오는가.
>
> 저장·전송·서빙 설계는 이 문서 밖이다(§10).

| 항목 | 값 |
|---|---|
| 상태 | 실측 완료 |
| 측정 기반 | nuScenes mini 10장면 · 196.5초 · 차량 1대분 전수 |
| 측정 재현 | `exploration/scripts/measure_batching.py`, `verify_mcap.py` |
| 최종 갱신 | 2026-08-25 |

**표기 규약** — "차량 N대"는 항상 **동시 스트림 N개**를 뜻한다. 원천을 수집한 실제 차량은
**2대**이므로 서로 다른 실차량 N대의 데이터는 존재하지 않는다(§2.3).

---

## 1. 무슨 데이터인가

자율주행 차량의 센서·차량신호·인지결과다. 성격이 완전히 다른 **세 계층**으로 갈리고,
이 비대칭이 시스템 설계 전체를 결정한다.

| 계층 | 내용 | 메시지/초 | 대역폭 |
|---|---|---|---|
| ① **신호** | CAN 버스, IMU, 조향, 차량 자세 | **1,295** | 432 KB/s |
| ② **인지 산출** | 3D 객체 박스, 트랙, 클래스 | 2.1 | 39 KB/s |
| ③ **원시 센서** | 카메라 6대 · LiDAR 1대 · 레이더 5대 | 158.8 | **27.15 MB/s** |

| 비교 | 중량(③) ÷ 경량(①②) |
|---|---|
| 대역폭 | **58배** |
| 메시지 건수 | 0.12배 — **경량이 8배 많다** |

**대역폭은 원시가 압도하는데 건수는 신호가 더 많다.** 둘을 한 경로로 처리하려는 순간
설계가 무너진다.

---

## 2. 원천 데이터

### 2.1 nuScenes (실측)

[nuScenes](https://www.nuscenes.org/)는 자율주행 전체 센서 스위트를 갖춘 공개 데이터셋이다.
합성이 아니라 **보스턴·싱가포르 실도로에서 수집된 실측 데이터**이며, 원래 타임스탬프대로
재생해 실시간 스트림으로 쓴다.

| 항목 | 값 |
|---|---|
| 장면(scene) | 1,000개 × **각 약 20초** |
| **수집 차량** | **2대** (`n015`, `n008`) |
| **총 주행시간** | 약 **5.4시간** |
| 수집 기간 | 2018-07-24 ~ 2018-11-21 (8일) |
| 수집 지역 | boston-seaport, singapore-onenorth, singapore-queenstown, singapore-hollandvillage |
| 카메라 | 6대 (FRONT / FRONT_LEFT / FRONT_RIGHT / BACK / BACK_LEFT / BACK_RIGHT) |
| LiDAR | 1대 (Velodyne HDL32E, 32빔) |
| 레이더 | 5대 (FRONT / FRONT_LEFT / FRONT_RIGHT / BACK_LEFT / BACK_RIGHT) |
| 키프레임 | **2.06Hz** — 6센서 동기화 시점. 3D 라벨은 여기에만 붙는다 |
| 라벨 | 1.4M 3D 박스 / 40k 키프레임, 23개 클래스 |
| 규모 | 전체 약 535GB · mini 10장면 **4.17GB** |
| CAN bus 확장 | 별도 다운로드 745MB. **인증 불필요** |

**라이선스**: 비상업 연구용(Motional 약관). **재배포 금지** — 데이터 파일을 저장소에
커밋하지 않는다.

### 2.2 두 가지 규모 제약 — 총량과 연속성

**둘은 다른 문제다.**

| | 값 | 조절 가능한가 |
|---|---|---|
| **총량** | 5.4시간 | ✅ 동시 스트림 수로 나뉜다 |
| **연속 구간** | **약 20초** | ❌ **늘릴 방법이 없다** |

연속 구간이 20초인 이유는 nuScenes가 연속 주행 로그가 아니라 **긴 주행에서 "흥미로운
20초"만 골라낸 큐레이션 데이터셋**이기 때문이다. 같은 `log`(같은 차량·같은 날)의
장면들조차 이어지지 않는다 — mini 실측:

```
log n015-2018-11-21-19-38-26   차량 n015   장면 3개
  scene-1077   20.0초
  scene-1094   19.5초  ← 앞 장면과 간격 460.1초 (7분 40초)
  scene-1100   19.5초  ← 앞 장면과 간격 120.5초 (2분)
```

인접 장면 간격이 최소 120.5초다. **20초 이내로 붙은 쌍은 0건.**

> 정확한 정신 모델: **5.4시간짜리 주행이 아니라, 20초짜리 주행 1,000개다.**
> 한 대로 몰아 재생해도 차량이 20초마다 다른 장소로 순간이동한다.

**용도별 영향**

| 용도 | 20초 제약 |
|---|---|
| 처리량·유실·중복 검증 | ✅ 무해 — 건수와 동시성의 문제이고 연속성과 무관 |
| 장시간 안정성(메모리 누수, 상태 누적) | ✅ 무해 — 반복이라도 시간만 길면 된다 |
| 관제 화면 | ⚠️ **20초마다 차량이 점프하는 것이 보인다** |
| 궤적 예측·장기 거동 학습 | ❌ 연속 필요 |
| 지오펜스 체류 등 시간 누적 분석 | ❌ 연속 필요 |

또한 **트리거 클립이 실제 fleet의 동작 방식**이다 — 차량 1대의 27.15 MB/s는 LTE 실효
대역폭(약 12.5 MB/s)을 넘어 연속 업로드가 물리적으로 불가능하므로, 실제 차량은 온보드
링버퍼에 기록하고 이벤트 전후 20~30초만 올린다. 공개 데이터셋이 대부분 클립 구조인
이유다(nuScenes 20초, Waymo Open Motion 20초, Argoverse 2 15초).

연속 데이터가 필요해지면 상위 원천은 **nuPlan**이다 — 같은 팀(Motional),
1,200~1,500시간, 약 15,000개의 **수 분 단위 연속 로그**. 단 원시 센서가 있는 것은
120시간(전체의 10%, 약 16TB)뿐이다.

### 2.3 "N대"는 동시 스트림 N개다

원천 차량이 2대이므로 **서로 다른 실차량 N대의 데이터는 존재하지 않는다.** 재생기가
장면에 가상 차량 id(`AV-000N`)를 붙여 N개 스트림을 동시에 흘리는 것이다.

**실제 N대와 구별되지 않는 것** — 서로 다른 키 N개로 파티셔닝, 시간축 뒤섞임, 총 처리량
N배, 동시성·백프레셔·순서·중복제거가 동일하게 걸린다. 파이프라인은 스트림이 실차량에서
왔는지 재생기에서 왔는지 알 수 없다.

**구별되는 것** — 지리 분포(모든 차량이 같은 4개 지역), 내용 독립성(서로 다른 차량이 같은
물리 차량의 주행을 재생), 차량 간 상관(실제 fleet은 서로를 보고 도로를 공유하나 여기선 독립).

앞의 셋은 처리량·유실·중복 검증에 무해하고 관제 화면에는 유해하다.

### 2.4 2차 원천 — CARLA + OpenSCENARIO

**폐기가 아니라 역할 분리**다. nuScenes는 "실제로 무슨 일이 일어났는가"를 주고, CARLA는
"**실주행에 부족한 상황을 의도적으로 만든다**". §7.2의 태그 희소성 측정이 이 필요를
실측으로 확인했다 — 기상 축은 실데이터만으로 채울 수 없다.

로컬 제약: CARLA는 x86 + GPU를 요구해 Apple Silicon에서 실행이 어렵다.

---

## 3. 채널별 실측 — 몇 Hz로, 어떤 크기로, 어떤 형식으로

### 3.1 ③ 원시 센서 (12채널)

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

키프레임과 스윕의 구성 — `sample_data` 전체 31,206건 중 키프레임은 4,848건(15.5%),
바이트로는 13.6%다. **원시 데이터의 86%가 스윕(비키프레임)** 이므로 무손실 보존에는
스윕이 반드시 포함돼야 한다.

### 3.2 ① 신호 (CAN + ego_pose), 채널 네이티브 주기

3장면 60초 실전 추출 기준(신호 77,714건).

| 채널 | 형식 | Hz | 필드 |
|---|---|---|---|
| **`zoesensors`** | JSON | **937.4** | `brake_sensor`, `steering_sensor`, `throttle_sensor` |
| `ms_imu` | JSON | 97.0 | `linear_accel`, `q`, `rotation_rate` |
| `zoe_veh_info` | JSON | 96.9 | 차량 정보 8종 |
| `steeranglefeedback` | JSON | 94.2 | `value` (rad) |
| `pose` | JSON | 48.3 | `pos`, `vel`, `accel`, `orientation`, `rotation_rate` |
| `ego_pose` | JSON | 19.5 | `translation`, `rotation`(쿼터니언) + 파생 `lat`/`lon` |
| `vehicle_monitor` | JSON | 2.0 | `vehicle_speed`, `yaw_rate`, `steering`, `brake`, `throttle`, `gear_position`, `rear_left_rpm`, `rear_right_rpm`, `battery_level`, 방향지시등 |
| **합계** | | **1,295.2 rec/s** | 평균 레코드 **342 B** |

> ⚠️ **`zoesensors`가 937Hz다.** 샘플 간격이 **0.25ms**까지 내려간다 — 페달·조향 원시
> 센서를 밀리초 이하로 뽑는다. 이 한 채널이 신호 레코드의 **72%** 를 차지한다.
> 설계 초안은 `ms_imu` 100Hz가 최고인 줄 알았으나 실제로는 9배 높은 채널이 있었다.

`ego_pose`는 `sample_data`마다 존재하므로 전 채널을 세면 158.8Hz까지 올릴 수 있다. 다만
같은 순간의 자세를 센서 수만큼 중복 기록하는 셈이라 **LIDAR 체인 한 줄(19.5Hz)** 을 쓴다.
이 선택으로 신호 총계가 1,295 rec/s가 된다(전 채널이면 1,434).

### 3.3 ② 인지 산출

| 항목 | 실측 |
|---|---|
| 키프레임 주기 | **2.06Hz** (평균 간격 0.504초) |
| 키프레임당 객체 | 평균 **45.9개**, 최대 **156개** |
| 객체 발생률 | **94.3 객체/초** |
| 메시지 형식 | 키프레임당 1건, 객체 배열을 담음 |
| 대역폭 | 39 KB/s (객체 레코드 약 420B) |

### 3.4 규모 환산

N = 동시 스트림 수(§2.3).

```
신호 레코드/초  = 1,295 × N
신호 대역폭     = 432 KB/s × N
원시 대역폭     = 27.15 MB/s × N
```

| N | 신호 rec/s | 신호 대역폭 | 원시 대역폭 | 원시 하루 축적 |
|---|---|---|---|---|
| 1 | 1,295 | 432 KB/s | 27 MB/s | 2.3 TB |
| 10 | 12,950 | 4.3 MB/s | 272 MB/s | 23.5 TB |
| 100 | 129,500 | 43.2 MB/s | 2,715 MB/s | 235 TB |

> ⚠️ 위 표는 **곱셈**이다. 부하 시험 결과가 아니다.

**목표 N은 이 문서에서 정하지 않는다.** 원천이 차량 2대이므로 어떤 N도 데이터에서
도출되지 않는다.

---

## 4. 필드 계약

계층별로 필드·타입·제약을 고정한다. 직렬화 포맷은 이 문서 밖이다(§10).

### 4.0 전송 헤더 — 모든 레코드 공통

스트림에 올라가는 모든 레코드가 공유하는 셋이다. **이 3튜플이 자연 키이자 dedup 키다.**

| 필드 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `vehicle_id` | string | NOT NULL, 파티션 키 | 가상 차량 id(§2.3) |
| `boot_id` | string(UUID) | NOT NULL, **스트림 헤더에 1회** | 온보드 로그의 생애 식별자. 로그가 사라지면 바뀐다 |
| `seq` | long | NOT NULL, 차량별 단조 증가 | 온보드 로그가 append 시점에 발급 |

`seq`는 **유일성뿐 아니라 연속성**을 준다. 결번이 곧 유실이므로 유실을 탐지할 수 있고,
"어디까지 봤는가"를 정수로 들 수 있어 dedup 상태가 데이터 양이 아니라 차량 수에
비례한다. 설계·실측은 [ack·dedup 설계](ack-dedup-design.md).

> **`event_id`(ULID)를 제거했다.** dedup 키·멱등 upsert 키·추적 id 세 용도가 모두
> `(vehicle_id, boot_id, seq)`로 대체된다. 3튜플은 **정렬 가능**해서 오히려 낫고,
> 레코드당 약 22 B가 줄고, 초당 647k회의 ULID 생성이 없어진다. 근거는
> [ack·dedup 설계](ack-dedup-design.md) §3.8.

`boot_id`가 레코드가 아니라 스트림 헤더에 실리는 이유 — 한 스트림 안에서는 불변이다.
저장 계층에서는 열로 펼쳐 3튜플을 완성한다.

### 4.1 신호 (`vehicle-signal`)

레코드 하나가 **한 채널의 한 샘플**이다. 채널마다 필드가 다르므로 공통 헤더 + 채널별
값 맵 구조를 쓴다.

| 필드 | 타입 | 제약 | 설명 |
|---|---|---|---|
| §4.0 전송 헤더 | — | PK = `(vehicle_id, boot_id, seq)` | |
| `scene_id` | string | NOT NULL | 소속 장면 |
| `channel` | string | NOT NULL | `zoesensors` / `ms_imu` / `pose` / `ego_pose` / … (§3.2) |
| `sensor_time` | timestamp-micros | NOT NULL | **센서 클럭.** 정본 시간축 |
| `log_time` | timestamp-micros | NOT NULL | 온보드 기록 시각 |
| `values` | map\<string, …\> | NOT NULL | 채널별 값 (§3.2 필드 참조) |

`ego_pose` 채널의 `values`는 다음을 포함한다.

| 키 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `translation` | array\<double\>[3] | z는 항상 0 | **ENU 로컬 미터** — 위경도 아님(§6) |
| `rotation` | array\<double\>[4] | \|q\| ≈ 1 | 쿼터니언 (w, x, y, z) |
| `lat` / `lon` | double | nullable | WGS84 파생(§6). 변환 실패 시 null |
| `location` | string | NOT NULL | 4개 지역 중 하나 |

CAN 채널의 주요 값 제약:

| 키 | 채널 | 제약 |
|---|---|---|
| `value` (조향각) | `steeranglefeedback` | **[-7.7, 6.3] rad** — 전체 데이터셋 기준. 비대칭이고 ±π를 넘는다(바퀴 각도가 아니라 조향 휠 회전각) |
| `vehicle_speed` | `vehicle_monitor` | >= 0 |
| `rotation_rate` | `ms_imu` | array[3], z가 yaw rate |

### 4.2 인지 산출 (`perception-object`)

| 필드 | 타입 | 제약 | 설명 |
|---|---|---|---|
| §4.0 전송 헤더 | — | PK = `(vehicle_id, boot_id, seq)` | |
| `scene_id` / `sample_id` | string | NOT NULL | 장면 / 키프레임 |
| `vehicle_id` | string | NOT NULL | 관측한 ego 차량 |
| `sensor_time` | timestamp-micros | NOT NULL | 키프레임 시각 |
| `track_id` | string | NOT NULL | **동일 객체의 시간축 연속 식별자** |
| `category` | string | NOT NULL | `vehicle.car`, `human.pedestrian.adult` 등 23종 |
| `attribute` | string | nullable | `vehicle.moving` / `vehicle.parked` / `pedestrian.moving` 등 |
| `center_x/y/z` | double | NOT NULL | 박스 중심 (**글로벌 프레임**, m) |
| `size_w/l/h` | double | > 0 | **(width, length, height)** 순서 — §9.3에서 실측 확정 |
| `rot_w/x/y/z` | double | \|q\| ≈ 1 | 박스 자세 쿼터니언 |
| `visibility` | string | NOT NULL | `v0-40` / `v40-60` / `v60-80` / `v80-100` |
| `num_lidar_pts` | int | >= 0 | 박스 내 LiDAR 포인트 수 — **라벨 신뢰도 프록시**(§7.1) |
| `num_radar_pts` | int | >= 0 | 박스 내 레이더 포인트 수 |

### 4.3 원시 로그 참조 (`segment-ref`)

원시 센서는 27.15 MB/s이므로 메시지에 실을 수 없다. 파일은 별도 보관하고 **참조와
메타데이터만** 레코드로 만든다.

> **용어 — 세그먼트와 참조는 다른 것이다.**
>
> | 용어 | 실체 | 크기 | 사는 곳 |
> |---|---|---|---|
> | **세그먼트** | 로그 파일 자체. 한 차량의 한 시간구간 전체 센서 기록 | ~357 MB | 오브젝트 스토리지 |
> | **`segment-ref`** | 그 파일을 **가리키는 참조 레코드** | < 2 KB | 메시지 버스 · 질의 저장소 |
>
> 이 스키마를 처음 `log-segment`라 불렀는데, 이름이 "이것이 세그먼트다"처럼 읽혀 파일과
> 혼동됐다. **참조임을 이름에 박아** `segment-ref`로 고쳤다. Claim-Check 비유로는
> 세그먼트가 창고에 맡긴 짐이고 `segment-ref`가 보관증이다.
>
> "세그먼트"라 부르는 이유 — 실제 차량은 **연속 녹화**하므로 업로드하려면 유한한 덩어리로
> 잘라야 하고, 그 조각이 세그먼트다. *"더 긴 스트림의 일부"* 라는 뜻이 단어에 들어 있다.

| 필드 | 타입 | 제약 | 설명 |
|---|---|---|---|
| §4.0 전송 헤더 | — | PK = `(vehicle_id, boot_id, seq)` | |
| `segment_id` | string(ULID) | UNIQUE | **파일의 정체**다. 전송 헤더가 레코드의 정체라면 이쪽은 blob의 정체이므로 둘 다 필요하다 |
| `scene_id` | string | NOT NULL | |
| `blob_uri` | string | NOT NULL | 로그 파일 위치 |
| `t_start` / `t_end` | timestamp-micros | NOT NULL | 세그먼트 시간 범위 |
| `sensor_channels` | array\<string\> | NOT NULL | 포함 채널 목록 |
| `size_bytes` | long | > 0 | |
| `checksum` | string | NOT NULL | sha256 — 무결성 검증 |
| `sample_count` | int | > 0 | |
| **`calibration`** | map | NOT NULL | **채널별 센서 외부/내부 파라미터.** 없으면 로그만으로 3D 재구성이 불가능하다(§6.2) |

### 4.4 실패 격리 (`dlq-envelope`)

이미 확정돼 있다 — `schemas/dlq-envelope.avsc`. 필드: `original_payload`(원본 바이트
무손실 보존), `error_class`(4분류 enum), `error_detail`, `source_subscription`,
`pipeline_step`, `processing_time`, `attempt`.

`error_class` 4분류: `PARSE_FAILURE` / `SCHEMA_VALIDATION_FAILURE` /
`BUSINESS_RULE_FAILURE` / `SINK_WRITE_FAILURE`.

---

## 5. 시간 계약

센서 주기가 **937Hz부터 2Hz까지 468배** 범위에 걸쳐 있고 각자 다른 클럭을 쓴다. 어느
카메라 프레임과 어느 LiDAR 스윕이 같은 순간인지 정의하지 않으면 조인이 성립하지 않는다.

### 5.1 타임스탬프 3종

| 타임스탬프 | 부여 주체 | 용도 |
|---|---|---|
| `sensor_time` | 센서 자체 클럭 | **정본 시간축** — 파티션·정렬 기준 |
| `log_time` | 온보드 기록 시점 | 온보드 버퍼링 지연 관측 |
| `ingest_time` | 수신 시점 | 전송 지연 `ingest_time - sensor_time` |

### 5.2 동기화 앵커 = 키프레임(2.06Hz)

nuScenes가 6센서를 정렬하는 단위이며 3D 라벨도 여기에만 붙는다. 센서 간 조인은 키프레임을
기준으로 하고, 그 사이 고주파 신호는 해당 키프레임 구간에 귀속시킨다.

### 5.3 지연 데이터는 폐기하지 않는다

watermark를 넘겨 도착해도 `sensor_time` 파티션에 그대로 적재한다. 유실 0 요구와 정합하는
유일한 선택이다.

---

## 6. 좌표 계약

### 6.1 ENU → WGS84

**`ego_pose.translation`은 위경도가 아니다.** 지역 지도의 **ENU(East-North-Up) 로컬 미터
좌표**이고 `z`는 항상 0이다.

| 계층 | 좌표 표현 |
|---|---|
| 원본 보존 | ENU 미터 **그대로** — 변환 오차를 원본에 섞지 않는다 |
| 정제 | ENU 원본 **+** 파생 `lat`/`lon` (변환 실패 시 null, 행은 유지) |

원점은 각 지도의 **남서쪽 모서리**이며, `nuscenes-devkit`
`map_expansion/map_api.py` 45–49행의 **공식 문서화 값**이다.

| 지역 | 원점 (lat, lon) |
|---|---|
| boston-seaport | 42.336849169438615, -71.05785369873047 |
| singapore-onenorth | 1.2882100868743724, 103.78475189208984 |
| singapore-hollandvillage | 1.2993652317780957, 103.78217697143555 |
| singapore-queenstown | 1.2782562240223188, 103.76741409301758 |

**"보스턴 1.35배 스케일링"의 정체** — 커뮤니티에 떠도는 이 보정은
**Web Mercator(EPSG:3857) 축척계수 `1/cos(lat)`** 이었다.

| 지역 | 원점 위도 | `1/cos(lat)` |
|---|---|---|
| boston-seaport | 42.34° | **1.3528** ← 보고된 "1.35" |
| singapore 3곳 | ~1.29° | 1.0003 (사실상 1) |

싱가포르는 적도 근처라 보정이 불필요했고 보스턴만 필요했던 것이다. **로컬 접평면 또는
대권 방식으로 직접 변환하면 어떤 보정 상수도 필요 없다.** 구현은
`exploration/fleetsentinel_ingest/geo.py`.

lat/lon 순서 규약 — GeoJSON은 `[lon, lat]`, 대부분의 지도 라이브러리와 DB 함수는
`(lat, lon)` 또는 `(lon, lat)` 중 하나를 고정한다. **경계를 넘을 때마다 순서를 명시한다.**

### 6.2 프레임이 셋이다 — 캘리브레이션이 필수

| 데이터 | 프레임 |
|---|---|
| LiDAR·레이더 점군 | **센서 프레임** |
| 인지 3D 박스 | **글로벌 프레임** |
| ego 자세 | 글로벌 프레임 |

**센서 외부 파라미터(extrinsics)가 없으면 이 셋을 정렬할 수 없다.** 즉 원시 로그를
보관하더라도 캘리브레이션이 함께 없으면 3D로 재구성이 불가능하다. `segment-ref`의
`calibration` 필드(§4.3)가 이 문제의 답이다.

---

## 7. 관측된 데이터 품질

### 7.1 라벨의 23.1%가 LiDAR 미관측

`num_lidar_pts = 0`인 주석이 **18,538건 중 4,278건 (23.1%)** 이다. LiDAR가 한 점도
맞히지 못한 객체다.

**라벨 넷 중 하나**이므로 예외 처리가 아니라 **주요 품질 축**으로 다뤄야 한다. 학습셋에
그대로 넣으면 안 되고, 저신뢰 플래그로 분류해 별도 취급한다.

거리와의 관계도 확인했다 — `num_lidar_pts=0` 객체의 평균 거리가 관측된 객체보다 멀다
(46.3m 대 37.1m). 물리적으로 일관된다.

### 7.2 시나리오 태그가 희소하다

`scene.description` 자유 텍스트에서 태그를 뽑은 결과(mini 10장면):

| 태그 | 출현 |
|---|---|
| 보행자 | 8 / 10 |
| 자전거 · 교차로 · 버스 | 5 / 10 |
| 트럭 | 4 / 10 |
| 야간 · 공사 · 주차 | 3 / 10 |
| **활성 강우** | **1 / 10** |
| **주간 명시** | **0 / 10** |

10장면 전부에서 태그가 하나 이상 나오지만 두 축이 약하다.

- **`day`는 명시되지 않는다.** "Night"만 기재되므로 주간은 *"night이 없으므로 day"* 라는
  **부정 추론**이다. 그렇게 기록해야 한다.
- **`after rain` ≠ 활성 강우.** scene-1094는 "Night, after rain"으로 노면은 젖었지만 비는
  오지 않는다. 정규식도 **부정 후방탐색**이 필요하다(`(?<!after\s)rain` — 전방탐색으로
  짜면 "after rain"을 활성 강우로 오분류한다).

**귀결**: 기상 축은 mini 규모에서 사실상 쓸 수 없다(활성 강우 1/10). 시뮬 보강(§2.4)이
가설이 아니라 **실측된 필요**다.

### 7.3 검증 규칙

| 규칙 | 대상 | 위반 시 |
|---|---|---|
| 조향각 ∈ [-7.7, 6.3] rad | 신호 | `BUSINESS_RULE_FAILURE` → DLQ |
| 속도 >= 0 | 신호 | `BUSINESS_RULE_FAILURE` → DLQ |
| 쿼터니언 \|q\| ≈ 1 | 신호·인지 | `BUSINESS_RULE_FAILURE` → DLQ |
| 박스 크기 > 0 | 인지 | `BUSINESS_RULE_FAILURE` → DLQ |
| `sensor_time` 단조성 (차량별) | 신호 | 경고 태그 — **폐기 안 함**(무손실) |
| `num_lidar_pts` = 0 | 인지 | 행 유지 + 저신뢰 플래그 |
| 키프레임에 6센서 미충족 | 원시 | 세그먼트에 센서 결손 플래그 |
| `checksum` 불일치 | 원시 | `SINK_WRITE_FAILURE` → 재업로드 |

---

## 8. 이 데이터를 무엇에 쓰는가

| 계층 | 쓰이는 곳 |
|---|---|
| 신호: 자세·lat/lon | 차량 위치·궤적 표시, 타임스탬프 역전 검출 |
| 신호: 속도·가속도 | 급제동 이벤트, 거동 조건 태그, 물리 범위 검증 |
| 신호: 조향·yaw rate | 좌/우회전 시나리오 태그 |
| 인지: 박스·클래스 | **학습셋 본체**, 객체 수·클래스 분포 지표 |
| 인지: `track_id` | 컷인·추월 등 **객체 상호작용 마이닝** |
| 인지: `visibility`·`num_lidar_pts` | 난이도 계층화, 라벨 신뢰도 |
| 원시: 카메라·LiDAR·레이더 | 센서 재생, 학습 입력, 센서 결손 검출 |
| `segment-ref` | 클립 검색 결과의 재생 진입점 |

목표는 **조건을 걸어 학습용 클립을 검색하고, 그 집합을 재현 가능하게 고정하는 것**이다.
"야간 + 우천 + 보행자 컷인" 같은 조건으로 클립을 찾아내는 작업이 성립하려면 인지 산출이
질의 가능한 형태로 색인돼 있어야 한다.

구체적 저장·질의·서빙 설계는 이 문서 밖이다(§10).

---

## 9. 검증

측정과 검증은 재현 가능해야 한다. 도구는 `exploration/`에 있고, 그 디렉터리는
**파이프라인 구현이 아니라 이 문서의 근거를 만드는 측정 도구**다.

### 9.1 좌표 변환

| 검사 | 결과 |
|---|---|
| ENU→WGS84→ENU 왕복 | 최대 오차 **1e-6 mm** |
| 지도 래스터 범위 대조 (10px/m) | **10/10 장면**이 범위 내 — 원점·스케일 정합 |
| 거리 보존 (haversine 대 ENU) | 오차 **≤ 0.014%** |
| 독립 구현 교차 대조 | 최대 편차 **36cm** (싱가포르 2cm) |
| 계약 테스트 | pytest **30건** |

### 9.2 무손실 보존

원시 센서 전량이 담겼는지 정본(`sample_data`)과 대조한다.

| 장면 | 담긴 수 | 정본 | 판정 |
|---|---|---|---|
| scene-0061 | 2,963 (키프레임 468 + 스윕 2,495) | 2,963 | ✅ |
| scene-0103 | 3,063 (480 + 2,583) | 3,063 | ✅ |
| scene-0553 | 3,171 (492 + 2,679) | 3,171 | ✅ |

초기 구현이 **키프레임만 담아 86%를 누락**했던 이력이 있다. 무손실 주장이 검증 없이 통과한
경로였으므로 상설 게이트를 붙였다 — `verify_mcap.py <dir> <dataroot>`.

### 9.3 좌표 체인 종단 검증 (결정적)

3D 박스 안의 LiDAR 포인트를 직접 세어 nuScenes 라벨의 `num_lidar_pts`와 대조했다.

| 박스 축 순서 | 객체 | 총 오차 |
|---|---|---|
| **(l/2, w/2, h/2)** | 76건 | **0 / 31,911 = 0.0%** |
| (w/2, l/2, h/2) | 76건 | 18,508 / 31,911 = 58.0% |

**31,911개 포인트에 오차 0** — 근사가 아니라 정확한 일치다. 이 값이 맞으려면
`센서 프레임 → 캘리브레이션 → ego 자세 → 글로벌 → 박스 로컬` **다섯 단계가 전부**
정확해야 한다. 한 링크만 틀려도 일치하지 않으므로, **육안 확인 없이 좌표 체인 전체를
기계적으로 증명**할 수 있다.

부수 확정 — `size = (width, length, height)`이고 박스 로컬 x축은 길이 방향이다.
`vehicle.car` 348건 중앙값이 폭 1.94m / 길이 4.70m / 높이 1.65m로 실제 승용차 치수와 맞는다.

### 9.4 검증하지 않은 것

- full 데이터셋(1,000장면) 규모 — mini로만 측정했다
- 나머지 7개 장면의 기하 검증 — 동일 파이프라인이라 일반화했으나 전수는 아님
- 레이더 `.pcd` 페이로드 해석 — 형식만 확인하고 디코딩은 미구현

---

## 10. 이 문서 밖의 것

데이터가 아니라 **설계**에 속하는 것들이다. 여기서 다루지 않는다.

| 주제 | 어디에 |
|---|---|
| 전송 단위·유실 방지 | **결정** — 레코드 단위 + 온보드 WAL. [`wal-design.md`](wal-design.md) · [`ingestion-design-review.md`](ingestion-design-review.md) §4.1 |
| ack·중복 제거 | **결정** — Cumulative Acknowledgement(CACK) + `seq` 슬라이딩 윈도우. [`ack-dedup-design.md`](ack-dedup-design.md) |
| 프로토콜 (gRPC / MQTT / HTTPS) | **결정** — 고주파 gRPC 스트림, 저주파 MQTT, 중량 HTTPS resumable. [`ingestion-design-review.md`](ingestion-design-review.md) §4.6·§4.8 |
| 관제 화면·시각화 도구 | **구현** — React + MapLibre + uPlot + Rerun. [`frontend-tech-notes.md`](frontend-tech-notes.md) |
| 학습셋 버저닝 | **결정** — 불변 매니페스트(클립 id + 체크섬). Iceberg 스냅샷은 보류. [`sdd.md`](sdd.md) S-8 |
| 처리량 목표·재생 모드 | [`pipeline-notes-provisional.md`](pipeline-notes-provisional.md) — **§2·§3만 유효**, 전송 결정은 위에서 뒤집혔다 |
| 직렬화 포맷 (Avro / Protobuf / JSON) | 미정 — P2 |
| 저장 계층 테이블 정의·파티션·정렬 키 | 미정 — P3 (엔진은 ClickHouse로 결정) |
| 보존 기간·수명주기 | 미정 |

**§4의 필드 계약은 확정하되 직렬화 포맷은 미정**이라는 점이 중요하다. "어떤 칸이 있고
타입·제약이 무엇인가"는 데이터 사실이지만, "바이트로 어떻게 만드는가"는 전송 설계다.

이 표의 절반이 「미정」에서 「결정」으로 바뀐 것은 데이터 정의 이후 수집 계층을 설계했기
때문이다. **그 결정들은 이 문서로 들어오지 않는다** — 여기는 데이터 사실만 담는다.

---

## 참고

- [nuScenes: A multimodal dataset for autonomous driving (arXiv:1903.11027)](https://arxiv.org/abs/1903.11027)
- [nuScenes 공식 사이트](https://www.nuscenes.org/) · [스키마 정의](https://github.com/nutonomy/nuscenes-devkit/blob/master/docs/schema_nuscenes.md)
- [CAN bus 확장](https://github.com/nutonomy/nuscenes-devkit/blob/master/python-sdk/nuscenes/can_bus/README.md)
- [map_api.py — 지도 원점 좌표](https://github.com/nutonomy/nuscenes-devkit/blob/master/python-sdk/nuscenes/map_expansion/map_api.py)
- [nuPlan (연속 로그 상위 원천)](https://www.nuscenes.org/nuplan)
