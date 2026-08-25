# FleetSentinel

[한국어](README.md) | [English](README-en.md)

**자율주행 차량·로봇이 쏟아내는 멀티모달 센서 데이터를 수집·관제하고, 머신러닝 학습셋으로 큐레이션하는 데이터 플랫폼**입니다.

한 문장으로 줄이면 이렇습니다.

> 모델을 학습시키는 프로젝트가 아니라, **모델을 학습시킬 수 있는 데이터를 만드는 시스템**입니다.

![Java](https://img.shields.io/badge/Java_21-ED8B00?style=flat-square&logo=openjdk&logoColor=white)
![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Apache Kafka](https://img.shields.io/badge/Apache_Kafka-231F20?style=flat-square&logo=apachekafka&logoColor=white)
![Apache Flink](https://img.shields.io/badge/Apache_Flink-E6526F?style=flat-square&logo=apacheflink&logoColor=white)
![ClickHouse](https://img.shields.io/badge/ClickHouse-FFCC01?style=flat-square&logo=clickhouse&logoColor=black)
![Spring Boot](https://img.shields.io/badge/Spring_Boot_4-6DB33F?style=flat-square&logo=springboot&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?style=flat-square&logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)

> **Status:** 🚧 **수집 계층 설계 완료 · 클라우드 파이프라인 미구현** — 데이터 규모·형식 실측(P1), 차량 측 유실 방지 경로 설계·검증(WAL·ack·dedup), 관제 대시보드 구현까지 끝났습니다. 그 사이를 잇는 **Kafka→Flink→ClickHouse가 아직 비어 있습니다.**
> **문서:** [System Design Document](docs/sdd.md) · [데이터 설계](docs/data-design.md) · [프론트엔드 기술 정리](docs/frontend-tech-notes.md) · [수집 계층 검토](docs/ingestion-design-review.md) · [WAL 설계](docs/wal-design.md) · [ack·dedup 설계](docs/ack-dedup-design.md) · [파이프라인 잠정 노트](docs/pipeline-notes-provisional.md) · [실행 절차](RUN.md)

> **Motivation (Prior Art).** Qualcomm 기업 연계 캡스톤 **[AutoNotify](https://github.com/Qualcomm-Capstone)**(On-Device-AI 실시간 과속탐지)를 **개인적으로 확장**한 데이터 엔지니어링 프로젝트입니다. 발표에서 받은 현직자 피드백 — _「엣지에서 차량 한 대씩 이벤트를 잡아내는 건 잘 만들었어요. 그런데 실제 fleet 규모로 올리면 병목은 모델이 아니라 수집·저장·정제 파이프라인으로 넘어갑니다」_ — 을 계기로, 단일 차량 이벤트 처리를 **fleet 규모 멀티모달 센서 플랫폼**으로 일반화했습니다. (Qualcomm은 본 확장에 관여하지 않았습니다.)

## 이 프로젝트가 푸는 문제

자율주행 차량 1대가 만들어내는 데이터는 성격이 완전히 다른 **세 계층**으로 갈립니다 —
**신호**(CAN·IMU·조향), **인지 산출**(3D 박스·트랙), **원시 센서**(카메라 6대·LiDAR·레이더 5대).

두 가지 사실이 아키텍처 전체를 결정합니다.

1. **대역폭은 원시가 58배 무거운데, 메시지 건수는 신호가 8배 많습니다.** 하나의 파이프라인으로
   둘 다 처리하려는 순간 설계가 무너집니다.
2. **차량 1대의 원시 데이터가 LTE 실효 대역폭을 넘습니다.** 한 대조차 연속 업로드가 불가능합니다.

또한 원천 데이터에는 정직하게 밝힐 제약이 있습니다 — **수집 차량은 2대**이고 **연속 구간
상한은 약 20초**입니다. 따라서 이 저장소에서 **"차량 N대"는 동시 스트림 N개**를 뜻하며,
서로 다른 실차량 N대의 데이터가 아닙니다.

> 📊 **실측 수치(Hz·크기·형식·채널별 상세)와 원천 제약은 [데이터 설계](docs/data-design.md)가
> 정본입니다.** 이 README는 수치를 다시 적지 않습니다.

## 시스템 아키텍처

```
nuScenes 실측 (1000 scene × 20초)      [CARLA/OpenSCENARIO — 보강, 스트레치]
        │
   ┌────┴─────────────────────────┐
   │                              │
① ② 경량                      ③ 중량 (27 MB/s)
 레코드 단위 + WAL            트리거 클립 업로드
   │ gRPC 스트림 (누적 ack)      │ HTTPS resumable
   ▼                              ▼
Kafka 3-broker (RF=3/ISR=2)   오브젝트 스토리지 (MCAP 원본)
   │                              │
   ▼                              │
Flink exactly-once                │
 dedup keyBy(vehicle_id)+seq      │
 검증 → DLQ                       │
 좌표 파생 ENU→WGS84              │
   │                              │
   ▼                              │
ClickHouse ◀──── blob_uri 참조 ────┘
 신호·인지 시계열 · 클립 카탈로그
   │
   ▼
Spring Boot 4 API  (REST 질의 + SSE 실시간 푸시)
   │
   ▼
React 대시보드
 ├─ MapLibre     fleet 지도
 ├─ uPlot        신호 시계열
 └─ Rerun 웹뷰어  센서 재생 (카메라 6대 · 점군 · 3D 박스)
```

핵심은 **경량·중량 경로 분리(Claim-Check)** 입니다. 메시지 버스에는 참조와 메타데이터만
흐르고, 무거운 센서 원본은 오브젝트 스토리지로 직행합니다. 둘은 클립 카탈로그에서 만납니다.

## 핵심 설계 결정

| 문제 | 해결 |
|---|---|
| 대역폭 58배 차이 | **Claim-Check** — 참조만 버스로, 원본은 스토리지로 |
| 1대도 연속 업로드 불가 | **트리거 클립** — 온보드 링버퍼 + 이벤트 앞뒤 20초만 업로드 |
| 초당 천 건 넘는 잘린 메시지 | **레코드 단위 gRPC 스트림 + 온보드 WAL** — 배치는 축적 창만큼의 유실이라 뒤집었다 ([WAL](docs/wal-design.md)) |
| 센서 주기가 채널마다 수백 배 다름 | **타임스탬프 3종** + 키프레임 동기화 앵커 |
| 좌표가 위경도가 아님 | **공식 원점 기반 ENU→WGS84** (§S-5) |
| 원본이 그 자체로 재생돼야 함 | **MCAP + 캘리브레이션 내장** |
| at-least-once인데 유실 0 증명 | **누적 ack + `seq` 슬라이딩 윈도우 dedup** — 결번이 곧 유실 ([ack·dedup](docs/ack-dedup-design.md)) |
| 라벨 23%가 미관측 | **품질 플래그를 큐레이션 1급 축으로** |

전체 문제-해결 대응은 [SDD §2–§3](docs/sdd.md)에 1:1로 정리돼 있습니다.

## 기술 스택

| 계층 | 채택 | 버전 |
|---|---|---|
| 스트림 버스 | Apache Kafka (KRaft, 3-broker RF=3/ISR=2) | 4.x |
| 스트림 처리 | Apache Flink — exactly-once | 2.3 / Java 17 |
| 원시 로그 | 오브젝트 스토리지 + **MCAP** | — |
| 저장·질의 | **ClickHouse** | 26.3 LTS |
| API | **Spring Boot** | 4.0 / Java 21 |
| 프론트엔드 | React + Vite · **MapLibre GL** · uPlot · **Rerun 웹뷰어** | — |
| 실시간 푸시 | SSE | — |

**채택하지 않은 것** — Elasticsearch·Kibana(지리 인덱스가 불필요한 규모 + 자체 대시보드로
대체), 데이터 웨어하우스(time travel 7일 상한으로 학습셋 버저닝 불가), Iceberg(스냅샷
버저닝이 실제로 필요해질 때까지 보류 — REST 카탈로그 컨테이너만 남겨뒀습니다).
근거는 [SDD §4.1](docs/sdd.md).

Iceberg 보류에는 **값이 있습니다.** Flink의 Iceberg 싱크가 주는 체크포인트 단위 2PC 원자
커밋을 잃고, 대신 `ReplacingMergeTree` 멱등 upsert로 닫습니다. 그러면 exactly-once가
**쓰기 시점이 아니라 읽기 시점에 닫히므로** 질의가 `FINAL`을 써야 합니다
([SDD L-14](docs/sdd.md)).

Java 버전이 모듈마다 다르다 — Spring Boot 4는 Java 17~25를 지원하지만 Flink 2.3은 Java 17이
기본이고 21은 실험적입니다. 그래서 API는 Java 21, Flink 잡은 Java 17로 나눕니다.

## 검증

| 게이트 | 결과 |
|---|---|
| 좌표 변환 계약 (pytest) | 통과 — 30건 |
| 원시 데이터 무손실 보존 | 통과 — 정본 대조 3장면 누락 0 |
| **좌표 체인 종단 검증** | 통과 — 박스 내 LiDAR 포인트 대조 **오차 0** |
| **WAL 내구성 (SIGKILL 후 재개)** | 통과 — `seq` 결번 **0**, 13건 |
| **dedup 멱등·상태 크기** | 통과 — 데이터 50배에 상태 불변, 14건 |
| **ack 프로토콜 (SIGKILL 후 결과적 exactly-once)** | 통과 — 재전송량 예측 대조, 13건 |
| 프론트엔드 (vitest) | 통과 — 26건 |
| Kafka HA (브로커 하드 kill) | 통과 — 유실 0 |
| 인프라 스모크 | 통과 |

수치와 방법은 [데이터 설계 §9](docs/data-design.md)가 정본입니다. 좌표 종단 검증이
결정적인데, 다섯 단계 변환이 전부 맞아야만 라벨과 정확히 일치하기 때문입니다.

## 진행 상황

| 단계 | 범위 | 상태 |
|---|---|---|
| P0 | 로컬 인프라 (Kafka HA · Flink · ClickHouse · 오브젝트 스토리지) | ✅ |
| **P1** | **데이터 정의** — 규모·형식 실측, 좌표계 규명, 무손실 검증 | ✅ |
| **P1.5** | **수집 계층 설계 + 온보드 유실 방지** — WAL · 누적 ack · `seq` dedup | ✅ 재생기에서 검증 |
| **P1.6** | **관제 대시보드** — 지도 · 시계열 · 클립 검색 · 센서 재생 | ✅ 목업 스트림 |
| P2 | 스키마 3종 확정 · **레코드 단위** 재생기 → Kafka | 다음 |
| P3 | Flink 파이프라인 · ClickHouse 적재 | |
| P5 | Spring Boot API — 대시보드를 목업에서 실 API로 전환 | |
| P6 | 데이터엔진 (시나리오 마이닝 · 학습셋 매니페스트) | |
| P7 | 프로토콜 계층 실구현 (gRPC 게이트웨이 + MQTT 저주파) | |
| P8 | CARLA 보강 (스트레치) | |

**P1.5·P1.6이 P2보다 먼저 끝난 것은 계획이 아니었습니다.** 배치 결정을 재검토하다 수집
계층 전체가 바뀌었고, 그 설계를 실증하려면 코드가 필요했습니다. 대시보드는 "어떤 화면이
필요한가"가 저장 스키마를 규정하므로 먼저 만드는 편이 나았습니다. 자세한 사정은
[SDD §5.1](docs/sdd.md).

## 알려진 한계

정직하게 남겨둡니다. 전체 목록은 [SDD §4.2](docs/sdd.md)에 있습니다.

- **라이브 관제가 아닙니다.** nuScenes 재생이 대역폭·주기·형식을 재현하지만 실차량 연동은 없습니다.
- **차량 측 유실 방지는 재생기에서만 검증했습니다.** WAL·ack·dedup을 구현해 SIGKILL 후 결번 0을 확인했지만, 실제 차량 온보드 소프트웨어는 스코프 밖입니다. 전원 손실 창(그룹 커밋 10ms)도 남아 있습니다.
- **대시보드가 아직 목업 스트림으로 돕니다.** 실데이터에서 뽑은 픽스처를 설계상 전송 단위로 재생하므로 화면·성능은 실제와 같지만, Kafka→Flink→ClickHouse→API 경로는 P2–P5입니다.
- **원천이 차량 2대이고 연속 구간이 20초입니다.** "N대"는 동시 스트림 N개이며 실차량 N대가 아닙니다.
- **인프라 HA는 스코프 밖입니다.** 단일 호스트 3브로커라 broker-level failover만 실증합니다.
- **인지 모델을 만들지 않습니다.** 인지 산출은 nuScenes 라벨을 사용합니다.
- **레이더 페이로드 미해석** — `.pcd`를 MCAP에 싣기만 하고 파싱·시각화는 미구현입니다.

## 프로젝트 구조

```
FleetSentinel/
├── frontend/         # (React) 관제 대시보드 — 지도·시계열·클립 검색·센서 재생
├── exploration/      # (Python) 데이터 측정·검증 도구 + 차량 측 유실 방지 구현(WAL·ack·dedup)
├── flink-pipeline/   # (Java) Flink 스트림 처리 — P3에서 재작성
├── infra/            # docker-compose (Kafka ×3 · Flink · ClickHouse · MinIO · Iceberg REST)
├── schemas/          # Avro 정본 스키마
├── scripts/          # 인프라 스모크 · Kafka HA 데모
└── docs/             # 설계 문서 7종 — 아래 표
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
| [`docs/data-design.md`](docs/data-design.md) | **데이터 사실의 정본** — 실측 수치·필드 계약·시간/좌표 계약. 다른 문서는 여기를 링크만 합니다 |
| [`docs/ingestion-design-review.md`](docs/ingestion-design-review.md) | 수집 계층 재검토 — 배치를 뒤집은 과정, Kafka/Pub/Sub·gRPC/MQTT 선택 근거 |
| [`docs/wal-design.md`](docs/wal-design.md) | 온보드 WAL — 요구사항·문제·구현·실측 |
| [`docs/ack-dedup-design.md`](docs/ack-dedup-design.md) | 누적 ack 프로토콜 + `seq` dedup — 상태를 124.8GB에서 350KB로 |
| [`docs/frontend-tech-notes.md`](docs/frontend-tech-notes.md) | 프론트엔드 기술 포인트 24개 (면접 예상 질문 형식) |
| [`docs/pipeline-notes-provisional.md`](docs/pipeline-notes-provisional.md) | 잠정 노트 — §4·§6은 재검토에서 무효가 됐습니다 |

## 라이선스

[MIT License](LICENSE). nuScenes 데이터는 Motional의 비상업 라이선스를 따르며 본 저장소에 포함하지 않습니다.
