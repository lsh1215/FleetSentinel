# FleetSentinel

[한국어](README.md) | [English](README-en.md)

자율주행 차량에서 발생하는 신호와 센서 원본을 수집하고, 이상 상태와 관련 구간을
관제 화면에서 확인하는 플랫폼입니다.

![Java](https://img.shields.io/badge/Java_21-ED8B00?style=flat-square&logo=openjdk&logoColor=white)
![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Apache Kafka](https://img.shields.io/badge/Apache_Kafka-231F20?style=flat-square&logo=apachekafka&logoColor=white)
![Apache Flink](https://img.shields.io/badge/Apache_Flink-E6526F?style=flat-square&logo=apacheflink&logoColor=white)
![ClickHouse](https://img.shields.io/badge/ClickHouse-FFCC01?style=flat-square&logo=clickhouse&logoColor=black)
![Spring Boot](https://img.shields.io/badge/Spring_Boot_4-6DB33F?style=flat-square&logo=springboot&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?style=flat-square&logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)

문서: [System Design Document](docs/sdd.md) · [데이터 설계](docs/data-design.md) · [프론트엔드 기술 정리](docs/frontend-tech-notes.md) · [수집 계층 검토](docs/ingestion-design-review.md) · [WAL 설계](docs/wal-design.md) · [ack·dedup 설계](docs/ack-dedup-design.md) · [실행 절차](RUN.md)

## 배경

Qualcomm 기업 연계 캡스톤 [AutoNotify](https://github.com/Qualcomm-Capstone)의 실시간 과속
탐지 프로젝트에서 출발했습니다. 단일 차량의 이벤트 탐지를 fleet 규모로 확장하려면 수집,
저장, 운영을 별도로 설계해야 한다는 피드백을 받아 현재 구조로 확장했습니다.

## 이 프로젝트가 푸는 문제

자율주행 차량의 데이터는 **신호**(CAN·IMU·조향), **객체 메타데이터**(3D 박스·트랙),
**원시 센서**(카메라 6대·LiDAR·레이더 5대)로 나뉩니다.

세 데이터는 전송량과 메시지 수가 달라 같은 경로로 처리하기 어렵습니다.

1. 원시 센서 데이터는 신호보다 대역폭을 58배 더 사용하지만, 메시지 수는 신호가 8배 많습니다.
2. 차량 한 대의 원시 데이터가 LTE 실효 대역폭을 넘기 때문에 원본을 계속 전송할 수 없습니다.

입력 데이터는 2대의 차량에서 수집됐고, 가장 긴 연속 구간은 약 20초입니다. 이 저장소에서
**"차량 N대"는 N개의 동시 스트림**을 뜻합니다.

실측 수치(Hz·크기·형식·채널별 상세)는 [데이터 설계](docs/data-design.md)에 정리했습니다.

## 시스템 아키텍처

![FleetSentinel 시스템 아키텍처](docs/assets/fleetsentinel-architecture.png)

신호와 객체 메타데이터는 Kafka를 거쳐 처리하고, 원본 센서 파일은 오브젝트 스토리지에
저장합니다. Kafka에는 원본 파일의 참조만 기록하고, ClickHouse의 클립 카탈로그에서 두 경로를
연결합니다.

## 핵심 설계 결정

| 문제 | 해결 |
|---|---|
| 대역폭 58배 차이 | **Claim-Check** — 참조만 버스로, 원본은 스토리지로 |
| 1대도 연속 업로드 불가 | **트리거 클립** — 온보드 링버퍼 + 이벤트 앞뒤 20초만 업로드 |
| 메시지 전송 중단 후 복구 | **레코드 단위 gRPC 스트림 + 온보드 WAL** ([WAL](docs/wal-design.md)) |
| 센서 주기가 채널마다 수백 배 다름 | **타임스탬프 3종** + 키프레임 동기화 앵커 |
| 좌표가 위경도가 아님 | **공식 원점 기반 ENU→WGS84** (§S-5) |
| 원본이 그 자체로 재생돼야 함 | **MCAP + 캘리브레이션 내장** |
| 중복 전송과 누락 확인 | **Cumulative Acknowledgement(CACK) + `seq` 슬라이딩 윈도우 dedup** ([ack·dedup](docs/ack-dedup-design.md)) |
| ODD 이탈을 바로 확인 | **Flink keyed state/timer → Kafka alert → API SSE** |
| 경보 발생 구간의 원본 확인 | **클립 카탈로그의 `blob_uri` → 오브젝트 스토리지 원본 재생** |

## 기술 스택

| 계층 | 기술 | 역할 |
|---|---|---|
| 수집·버퍼링 | Apache Kafka | 차량 레코드를 받아 처리와 저장으로 분기하고, 장애 시 재처리할 수 있게 보관 |
| 스트림 처리 | Apache Flink | 차량별 상태를 유지하면서 중복 제거, 검증, 좌표 변환, ODD 이탈 감지 |
| 원본 저장 | 오브젝트 스토리지 + MCAP | 용량이 큰 센서 클립을 파일로 저장하고 API에서 다시 재생 |
| 시계열 저장 | ClickHouse | 신호·객체 메타데이터와 클립 카탈로그를 저장하고 조회 |
| API | Spring Boot | ClickHouse 조회와 Kafka 알림을 REST·SSE로 제공 |
| 관제 화면 | React · MapLibre GL · uPlot · Rerun | 차량 위치, 신호, 알림, 센서 클립을 한 화면에서 확인 |

신호와 객체 메타데이터는 Kafka·Flink·ClickHouse를 거치고, 원본 센서 파일은 오브젝트
스토리지에 저장합니다. 두 경로는 클립 ID와 `blob_uri`로 연결합니다.

## 알려진 한계

현재 범위와 한계는 [SDD §4.2](docs/sdd.md)에 정리했습니다.

- **라이브 관제가 아닙니다.** nuScenes 재생이 대역폭·주기·형식을 재현하지만 실차량 연동은 없습니다.
- **차량 측 유실 방지는 재생기에서만 검증했습니다.** WAL·ack·dedup을 구현해 SIGKILL 후 결번 0을 확인했지만, 실제 차량 온보드 소프트웨어는 스코프 밖입니다. 전원 손실 창(그룹 커밋 10ms)도 남아 있습니다.
- **대시보드는 기본 실행에서 목업 스트림을 씁니다.** `make dashboard`는 실 API에 연결되지만 Kafka→Flink→API 종단 지연과 복구는 아직 측정하지 않았습니다.
- **원천이 차량 2대이고 연속 구간이 20초입니다.** "N대"는 동시 스트림 N개이며 실차량 N대가 아닙니다.
- **인프라 HA는 스코프 밖입니다.** 단일 호스트 3브로커라 broker-level failover만 실증합니다.
- **3D 박스는 nuScenes 주석입니다.** 대시보드가 재생하는 객체 위치는 차량에서 계산한 값이 아니며 관제 화면의 주변 상황 표시에만 사용합니다.
- **레이더 페이로드 미해석** — `.pcd`를 MCAP에 싣기만 하고 파싱·시각화는 미구현입니다.

## 프로젝트 구조

```
FleetSentinel/
├── frontend/         # (React) 관제 대시보드 — 지도·시계열·클립 검색·센서 재생
├── exploration/      # (Python) 데이터 측정·검증 도구 + 차량 측 유실 방지 구현(WAL·ack·dedup)
├── flink-pipeline/   # (Java) dedup·검증·좌표 파생·ODD 이탈 판정
├── infra/            # docker-compose (Kafka ×3 · Flink · ClickHouse · MinIO)
├── schemas/          # Avro 스키마
├── scripts/          # 인프라 스모크 · Kafka HA 데모
└── docs/             # 설계 문서
```

## 실행

```bash
make up        # 로컬 스택 기동
make topics    # Kafka 토픽 부트스트랩
make smoke     # 인프라 검증
make ha-demo   # Kafka HA broker-kill 데모
```

```bash
cd exploration && ./setup-venv.sh && PYTHONPATH=. .venv/bin/python -m pytest tests/ -q   # 82건
cd frontend && npm install && npm run dev      # 대시보드 (목업 SSE 스트림)
```

측정·검증 도구와 차량 측 구현은 [`exploration/README.md`](exploration/README.md),
대시보드는 [`frontend/README.md`](frontend/README.md)를 참고하세요.

### 설계 문서

| 문서 | 무엇이 있는가 |
|---|---|
| [`docs/sdd.md`](docs/sdd.md) | 전체 시스템 설계 — 문제·해결 1:1 대응, 기각한 대안 12건, 알려진 한계 14건 |
| [`docs/data-design.md`](docs/data-design.md) | 실측 수치·필드 계약·시간/좌표 계약 |
| [`docs/ingestion-design-review.md`](docs/ingestion-design-review.md) | 수집 계층 재검토 — 배치를 뒤집은 과정, Kafka/Pub/Sub·gRPC/MQTT 선택 근거 |
| [`docs/wal-design.md`](docs/wal-design.md) | 온보드 WAL — 요구사항·문제·구현·실측 |
| [`docs/ack-dedup-design.md`](docs/ack-dedup-design.md) | Cumulative Acknowledgement(CACK) 프로토콜 + `seq` dedup — 상태를 124.8GB에서 350KB로 |
| [`docs/frontend-tech-notes.md`](docs/frontend-tech-notes.md) | 프론트엔드 기술 포인트 24개 (면접 예상 질문 형식) |
| [`docs/pipeline-notes-provisional.md`](docs/pipeline-notes-provisional.md) | 잠정 노트 — §4·§6은 재검토에서 무효가 됐습니다 |

## 라이선스

[MIT License](LICENSE). nuScenes 데이터는 Motional의 비상업 라이선스를 따르며 본 저장소에 포함하지 않습니다.
