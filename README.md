# FleetSentinel

[한국어](README.md) | [English](README-en.md)

**자율주행 차량·로봇이 쏟아내는 멀티모달 센서 데이터를 수집·관제하고, 머신러닝 학습셋으로 큐레이션하는 데이터 플랫폼**입니다.

한 문장으로 줄이면 이렇습니다.

> 모델을 학습시키는 프로젝트가 아니라, **모델을 학습시킬 수 있는 데이터를 만드는 시스템**입니다.

![Java](https://img.shields.io/badge/Java_21-ED8B00?style=flat-square&logo=openjdk&logoColor=white)
![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Apache Kafka](https://img.shields.io/badge/Apache_Kafka-231F20?style=flat-square&logo=apachekafka&logoColor=white)
![Apache Flink](https://img.shields.io/badge/Apache_Flink-E6526F?style=flat-square&logo=apacheflink&logoColor=white)
![Apache Iceberg](https://img.shields.io/badge/Apache_Iceberg-1F70C1?style=flat-square&logo=apacheiceberg&logoColor=white)
![Elasticsearch](https://img.shields.io/badge/Elasticsearch-005571?style=flat-square&logo=elasticsearch&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)

> **Status:** 🚧 **데이터 정의 단계** — 어떤 데이터가 어떤 규모·형식으로 들어오는지 실측 완료. 수집·ETL 파이프라인은 아직 설계하지 않았습니다.
> **문서:** [System Design Document](docs/sdd.md) · [데이터 설계](docs/data-design.md) · [파이프라인 잠정 노트](docs/pipeline-notes-provisional.md) · [실행 절차](RUN.md)

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
nuScenes 실측 (1000 scene × 20초)          [CARLA/OpenSCENARIO — 보강, Phase 8]
        │
   ┌────┴─────────────────────────┐
   │                              │
① ② 경량 268 KB/s            ③ 중량 27 MB/s
 100ms 창 배치                트리거 클립 업로드
   │ MQTT / gRPC                 │ HTTPS resumable
   ▼                              ▼
Kafka 3-broker (RF=3/ISR=2)   오브젝트 스토리지 (MCAP 세그먼트)
   │                              │
   ▼                              │
Flink exactly-once                │
 dedup keyBy(event_id)            │
 검증 → DLQ                       │
 좌표 파생 ENU→WGS84              │
   │                              │
   ├──▶ Iceberg Bronze ◀──────────┤  (원본 MCAP + 구조화 원본)
   ├──▶ Iceberg Silver            │
   └──▶ Elasticsearch             │
             │                    │
             ▼                    ▼
      Kibana Maps          클립 카탈로그 (Iceberg)
      fleet 관제          scene·시간범위·blob_uri·조건태그
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
              Rerun 센서 재생          학습셋 스냅샷 (time travel)
```

핵심은 **경량·중량 경로 분리(Claim-Check)** 입니다. 메시지 버스에는 참조와 메타데이터만
흐르고, 무거운 센서 원본은 오브젝트 스토리지로 직행합니다. 둘은 클립 카탈로그에서 만납니다.

## 핵심 설계 결정

| 문제 | 해결 |
|---|---|
| 대역폭 58배 차이 | **Claim-Check** — 참조만 버스로, 원본은 스토리지로 |
| 1대도 연속 업로드 불가 | **트리거 클립** — 온보드 링버퍼 + 이벤트 앞뒤 20초만 업로드 |
| 초당 천 건 넘는 잘린 메시지 | **시간창 배치** — 100ms 잠정 (전송 설계 영역, [잠정 노트](docs/pipeline-notes-provisional.md)) |
| 센서 주기가 채널마다 수백 배 다름 | **타임스탬프 3종** + 키프레임 동기화 앵커 |
| 좌표가 위경도가 아님 | **공식 원점 기반 ENU→WGS84** (§S-5) |
| 원본이 그 자체로 재생돼야 함 | **MCAP + 캘리브레이션 내장** |
| at-least-once인데 유실 0 증명 | **exactly-once 4단** + `event_id` 집합 대사 |
| 라벨 23%가 미관측 | **품질 플래그를 큐레이션 1급 축으로** |

전체 문제-해결 대응은 [SDD §2–§3](docs/sdd.md)에 1:1로 정리돼 있습니다.

## 기술 스택

**수집·처리** — Apache Kafka (KRaft, 3-broker RF=3/ISR=2) · Apache Flink 2.0 (Java 21, exactly-once) · MQTT / gRPC

**저장** — Apache Iceberg (Bronze/Silver) · MinIO / GCS (MCAP 원본) · **MCAP** (로보틱스 표준 로그 컨테이너)

**서빙** — Elasticsearch + Kibana Maps (fleet 관제) · **Rerun** (멀티모달 센서 재생, MIT/Apache-2.0)

**원천** — nuScenes (실측, 보스턴·싱가포르) · CARLA + OpenSCENARIO (시나리오 보강, 스트레치)

## 검증

| 게이트 | 결과 |
|---|---|
| 좌표 변환 계약 (pytest) | 통과 |
| 원시 데이터 무손실 보존 | 통과 — 정본 대조 3장면 누락 0 |
| **좌표 체인 종단 검증** | 통과 — 박스 내 LiDAR 포인트 대조 **오차 0** |
| Kafka HA (브로커 하드 kill) | 통과 — 유실 0 |
| 인프라 스모크 | 통과 |

수치와 방법은 [데이터 설계 §9](docs/data-design.md)가 정본입니다. 좌표 종단 검증이
결정적인데, 다섯 단계 변환이 전부 맞아야만 라벨과 정확히 일치하기 때문입니다.

## 진행 상황

| 단계 | 범위 | 상태 |
|---|---|---|
| P0 | 로컬 인프라 (Kafka HA·Flink·Iceberg·ES·Kibana) | ✅ |
| **P1** | **데이터 정의** — 규모·형식 실측, 좌표계 규명, 무손실 검증 | ✅ |
| P2 | 스키마 3종 확정 · 배치 재생기 → Kafka | 다음 |
| P3 | Flink 파이프라인 (dedup·검증·DLQ·싱크) | |
| P4 | Claim-Check · 클립 카탈로그 | |
| P5 | 관제 (Kibana fleet 지도 + Rerun) | |
| P6 | 데이터엔진 (시나리오 마이닝 · 학습셋 스냅샷) | |
| P7 | 프로토콜 계층 (MQTT / gRPC) | |
| P8 | CARLA 보강 (스트레치) | |

## 알려진 한계

정직하게 남겨둡니다. 전체 목록은 [SDD §4.2](docs/sdd.md)에 있습니다.

- **라이브 관제가 아닙니다.** nuScenes 재생이 대역폭·주기·형식을 재현하지만 실차량 연동은 없습니다.
- **원천이 차량 2대이고 연속 구간이 20초입니다.** "N대"는 동시 스트림 N개이며 실차량 N대가 아닙니다.
- **인프라 HA는 스코프 밖입니다.** 단일 호스트 3브로커라 broker-level failover만 실증합니다.
- **인지 모델을 만들지 않습니다.** 인지 산출은 nuScenes 라벨을 사용합니다.
- **레이더 페이로드 미해석** — `.pcd`를 MCAP에 싣기만 하고 파싱·시각화는 미구현입니다.

## 프로젝트 구조

```
FleetSentinel/
├── exploration/      # (Python) P1 데이터 탐색 — 측정·검증·재생 도구 (파이프라인 구현 아님)
├── flink-pipeline/   # (Java) Flink 스트림 처리 — P3에서 재작성
├── infra/            # docker-compose (Kafka·Flink·Iceberg·ES·Kibana·MinIO)
├── schemas/          # Avro 정본 스키마
├── scripts/          # 인프라 스모크 · Kafka HA 데모
└── docs/             # sdd.md · data-design.md
```

## 실행

```bash
make up        # 로컬 스택 기동
make topics    # Kafka 토픽 부트스트랩
make smoke     # 인프라 검증
make ha-demo   # Kafka HA broker-kill 데모
```

데이터 탐색 도구는 [`exploration/README.md`](exploration/README.md)를 참고하세요.
**이 디렉터리는 파이프라인 구현이 아닙니다** — 문서의 실측 수치를 뽑아낸 측정·검증 도구입니다.

## 라이선스

[MIT License](LICENSE). nuScenes 데이터는 Motional의 비상업 라이선스를 따르며 본 저장소에 포함하지 않습니다.
