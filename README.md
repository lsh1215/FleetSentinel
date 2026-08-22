# FleetSentinel

[한국어](README.md) | [English](README-en.md)

차량 **Fleet 규모의 실시간 텔레메트리**를 수집 → 정제 → 분석하는 데이터 엔지니어링 플랫폼입니다. 자체호스팅 OSS 스트리밍 레이크하우스(Kafka → Flink → Iceberg/BigQuery)와 Medallion(Bronze/Silver/Gold) 정제 계층을 중심으로, 대규모 원본 텔레메트리를 신뢰할 수 있는 분석 데이터로 정제하고, Elasticsearch(self-host)로 실시간 지도 시각화·이상탐지까지 제공합니다. **고throughput 스트림 처리는 Java(Flink), 글루·오케스트레이션은 Python, 변환은 SQL** 로 역할을 나눈 하이브리드 구성입니다.

![Java](https://img.shields.io/badge/Java_21-ED8B00?style=flat-square&logo=openjdk&logoColor=white)
![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![SQL](https://img.shields.io/badge/SQL-4479A1?style=flat-square&logo=postgresql&logoColor=white)
![Google Cloud](https://img.shields.io/badge/Google_Cloud-4285F4?style=flat-square&logo=googlecloud&logoColor=white)
![Apache Kafka](https://img.shields.io/badge/Apache_Kafka-231F20?style=flat-square&logo=apachekafka&logoColor=white)
![Apache Flink](https://img.shields.io/badge/Apache_Flink-E6526F?style=flat-square&logo=apacheflink&logoColor=white)
![BigQuery](https://img.shields.io/badge/BigQuery-669DF6?style=flat-square&logo=googlebigquery&logoColor=white)
![Apache Iceberg](https://img.shields.io/badge/Apache_Iceberg-1F70C1?style=flat-square&logo=apacheiceberg&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-FF694B?style=flat-square&logo=dbt&logoColor=white)
![Airflow](https://img.shields.io/badge/Apache_Airflow-017CEE?style=flat-square&logo=apacheairflow&logoColor=white)
![Elasticsearch](https://img.shields.io/badge/Elasticsearch-005571?style=flat-square&logo=elasticsearch&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)

> **Status:** 🔄 **v3.0 재설계 진행 중 — 자율주행 멀티모달 도메인으로 전환.**
>
> 아래 본문은 **v2.0(차량 OBD 텔레메트리)** 기준이며 히스토리로 남겨둔다. 현재 프로젝트는
> 자율주행 차량·로봇의 **멀티모달 센서 데이터**(카메라·LiDAR·레이더·CAN)를 수집·관제하고
> ML 학습셋으로 큐레이션하는 플랫폼으로 재설계 중이다.
>
> - **현행 데이터 설계 → [docs/data-design-v3.md](docs/data-design-v3.md)** (정본)
> - 설계 이력 → [docs/sdd.md](docs/sdd.md) (v2.0, §6은 위 문서로 대체됨)
> - 실행 절차 → [RUN.md](RUN.md)
>
> v2.0 구현 코드(합성 생성기·Flink 잡·OBD 서빙)는 도메인 전환으로 제거했다.
> 검증된 인프라 계층(Kafka 3-broker HA · Flink · Iceberg · ES/Kibana)과 Maven 의존성은 유지한다.

> **Motivation (Prior Art).** 본 프로젝트는 Qualcomm 기업 연계 캡스톤 **[AutoNotify](https://github.com/Qualcomm-Capstone)**(On-Device-AI 기반 실시간 과속탐지·알림 시스템)를 **개인적으로 확장**한 데이터 엔지니어링 프로젝트입니다. 캡스톤 발표에서 Qualcomm 현직자분께 받은 피드백 — _「엣지에서 차량 한 대씩 이벤트를 잡아내는 건 잘 만들었어요. 그런데 이걸 실제 fleet 규모, 수백·수천 대가 초당 계속 데이터를 쏘는 상황으로 올리면 병목은 모델이 아니라 수집·저장·정제 파이프라인으로 넘어갑니다. 그 스트림을 유실·중복 없이 감당하는 게 진짜 어려운 지점이에요.」_ — 을 계기로, AutoNotify의 엣지 → MQTT 이벤트 아키텍처를 **fleet 전체의 연속 텔레메트리를 다루는 데이터 플랫폼**으로 일반화했습니다. (Qualcomm은 본 확장에 관여하지 않았으며, 확장 설계·구현은 단독으로 진행했습니다.)

## 개요

데이터 엔지니어링의 본질은 데이터의 양을 줄이는 것이 아니라 **원본(raw) → 신뢰(trusted) → 활용(usable)** 로 정제하는 것입니다. FleetSentinel은 수천만 건의 원본 차량 텔레메트리를 무손실로 보존하고(Bronze), 중복·결측·이상치를 걷어내 신뢰할 수 있게 만들고(Silver), 목적별 지표로 집계해(Gold) 실시간 대시보드·이상탐지로 서빙합니다. AutoNotify가 **차량 1대의 이벤트**를 처리했다면, FleetSentinel은 이를 **fleet 전체의 연속 스트림**으로 확장하고, 규모 속에서 지연·유실·중복을 어떻게 다루는지를 명확하게 보여주는 데 초점을 둡니다.

## 언어 전략 (하이브리드)

DE 생태계는 오케스트레이션·변환·품질이 Python/SQL 표준이고, 고throughput·exactly-once 스트림 처리는 JVM 엔진이 강점입니다. 각 층을 **근거에 맞는 언어**로 배치했습니다.

| 계층 | 언어 | 이유 |
|---|---|---|
| 스트림 처리 코어 (Bronze/Silver) | **Java (Apache Flink)** | exactly-once·고throughput·타입안전, JVM 엔진 강점 |
| 텔레메트리 생성기 / 수집 글루 | **Python** | 빠른 작성, 생태계 |
| 변환 (Silver → Gold) | **SQL (dbt)** | DE 변환의 표준 + 데이터 품질 테스트 |
| 오케스트레이션 | **Python (Airflow)** | 생태계 표준 |

> 설계 근거는 [SDD ADR-001](docs/sdd.md#adr-001-하이브리드-언어-전략-javaflink--pythonsql-글루)에 기록.

## 시스템 아키텍처

핵심 아이디어는 **Kafka → Flink 다중 싱크(단일 잡 Fork)** 입니다. Kafka 토픽의 텔레메트리를 Flink 잡 하나가 ① 원본 보존(Iceberg Bronze/Silver) ② 실시간 서빙(Elasticsearch)으로 동시에 흘리고, ③ Gold(BigQuery)는 dbt가 BigLake로 Silver Iceberg를 조회해 별도 생성합니다.

<details>
<summary>텍스트 다이어그램 (상세)</summary>

```
[SUMO 시뮬레이터 N대 (LuST 시나리오)]   (Python 생성기, + 시간가속 → 수천만 이벤트)
        │  Avro binary 텔레메트리 (key = vehicle_id)
        ▼
   Apache Kafka (KRaft, self-host 단일호스트 3-broker, RF=3/ISR=2/acks=all)
        │  at-least-once
        ▼
 Apache Flink (JobManager+TaskManager · Java · 체크포인트 exactly-once)  (다중 싱크: Iceberg·Elasticsearch)
   │  · keyBy(event_id) dedup + 상태 TTL, Kafka 오프셋 정렬 커밋(2PC)
   │  · 스키마 검증 → 불량은 Dead-Letter Queue                              ▼
   │  · 지연 무기한 수용                                          Elasticsearch (self-host Basic, 단일 인덱스, 멱등 upsert)
   │  · 차량 메타 조인(enrich)                                    ├─ Kibana Maps (위치·속도 히트맵)
   ▼                                                              └─ Kibana Alerting (임계 초과 즉시 알림)
 ── Medallion (Lakehouse) ──
  Bronze  GCS + Apache Iceberg   (원본 append-only, 무손실 보존, Flink 네이티브 싱크)
  Silver  GCS + Apache Iceberg   (중복제거·타입정리·이상치·차량메타 조인 = 신뢰 1행, Flink 네이티브 싱크)
  Gold    BigQuery               (차량별 분당 평균속도·급브레이크 횟수·일일 연비·이상 플래그, BQ ML 이상탐지)
        │  dbt(SQL, BigLake로 Silver Iceberg 조회) 변환 + 데이터 품질 테스트(실패행 저장)
        │  Airflow 스케줄·의존성 (로컬 Airflow / 세션 시 GKE in-cluster, SDD §7.4/§12.7)
        ▼
  BigQuery Gold ──(BigQuery → ES 템플릿)──▶ Elasticsearch ──▶ Kibana 대시보드
```

</details>

## 핵심 아키텍처

다음 패턴을 사용합니다:

- **Medallion 아키텍처**: Bronze(원본 보존) → Silver(정제·신뢰) → Gold(목적별 집계)로 데이터 품질을 단계적으로 올림
- **Kafka → Flink 다중 싱크**: Flink 잡 하나가 원본 보존(Iceberg Bronze/Silver)·실시간 서빙(Elasticsearch)으로 동시 적재, Gold는 dbt가 BigLake로 별도 생성
- **역할 분리형 하이브리드 언어**: 스트림 코어 Java(Flink), 글루·오케스트레이션 Python, 변환 SQL(dbt) — 근거는 SDD ADR-001
- **Lakehouse**: Bronze/Silver는 GCS 위 Apache Iceberg(오픈 포맷·스키마 진화·time travel, Flink 네이티브 싱크), Gold는 BigQuery(dbt가 BigLake로 Silver Iceberg 조회)
- **정확히 한 번(exactly-once) 처리**: Flink 체크포인트(Kafka 오프셋 정렬 커밋 2PC) + Iceberg 원자 커밋, `keyBy(event_id)` dedup·상태 TTL
- **Kafka HA 데모**: 단일호스트 3브로커 RF3/ISR2 — 브로커 kill → 리더 재선출 → 유실 0 (인프라 HA·존/호스트 SPOF는 스코프 밖)
- **데이터 품질 게이트**: dbt 테스트(`unique`/`not_null`/`accepted_range`/`relationships`)로 규칙 위반 행을 저장·추적
- **무손실 보존**: 파싱 실패 레코드는 Dead-Letter Queue로 격리 (은닉 유실 0)
- **역할 분리**: BigQuery = 대규모 분석·이력(warehouse) + BQ ML 이상탐지, Elasticsearch = 실시간 검색·지도 (상보적)

## 기술 스택

**수집 & 스트림 처리**

- Apache Kafka (**KRaft, self-host**, 단일호스트 3-broker) — 수집 (RF=3 / min.insync.replicas=2 / acks=all)
- Apache Flink (**Java 21**, self-host JobManager/TaskManager) — exactly-once 스트림 처리 (Bronze/Silver, 체크포인트 → GCS)
- (선택) EMQX / HiveMQ — MQTT 브로커 → Kafka

**레이크하우스 & 변환**

- Google Cloud Storage + Apache Iceberg (Bronze / Silver, Flink 네이티브 싱크)
- BigQuery (Gold — dbt가 BigLake로 Silver Iceberg 조회)
- **dbt (SQL)** — 변환 + 데이터 품질 테스트
- **Airflow · Python** — 오케스트레이션 (로컬 Airflow / 세션 시 GKE in-cluster, SDD §7.4/§12.7)
- **BigQuery ML** (`ML.DETECT_ANOMALIES`, `ARIMA_PLUS`) — 이상탐지 (Gold 대상)

**서빙 & 분석**

- Elasticsearch (**self-host, Basic tier**, 단일 인덱스, `doc_id=event_id` 멱등 upsert)
- Kibana (Maps 지오 시각화, 대시보드, 규칙 기반 Alerting)

**관측성 & 인프라**

- Cloud Monitoring/Logging (기본) + Prometheus·Grafana·Loki·OpenTelemetry (로컬 개발 한정, SDD §10.2)
- Docker, Terraform (GCP), GitHub Actions (CI)

**데이터 소스**

- SUMO (TraCI) 트래픽 시뮬레이터 (**Python** 생성기) — fleet 규모·실시간
- Kaggle Levin OBD-II 주행 데이터 리플레이 — 현실성(실측 분포 보정, comma2k19는 검토 후 기각: docs/sdd.md §13 R-2 참고)

## Medallion 계층

| 계층 | 내용 | 저장소 |
|---|---|---|
| **Bronze** | Kafka 원본 이벤트를 가공 없이 append-only 적재 — 중복·널 포함 = "증거 보존"(스키마 불량은 DLQ로 무손실 격리) | GCS + Iceberg |
| **Silver** | 중복제거·스키마 검증·타입 정리·이상치 제거 + 차량 메타(모델/연식) 조인 → 이벤트당 깨끗한 1행 | GCS + Iceberg |
| **Gold** | 목적별 집계(차량별 분당 평균속도·급브레이크 횟수·일일 연비·이상 주행 플래그) — 원본의 수백~수천분의 1 | BigQuery (dbt) |

## 핵심 엔지니어링 도전

대규모 스트림을 정직하게 다루기 위해 해결한(할) 문제들입니다:

| 도전 | 접근 |
|---|---|
| 정확히 한 번 처리 + 중복제거 | Flink 체크포인트(Kafka 오프셋 정렬 커밋 2PC) + Iceberg 원자 커밋, `keyBy(event_id)` dedup·상태 TTL |
| Kafka 가용성(HA) | 단일호스트 3브로커 RF3/ISR2 — 브로커 kill → 리더 재선출 → 유실 0 (인프라 HA·존/호스트 SPOF는 스코프 밖) |
| 지연·순서역전(late/out-of-order) | 이벤트타임 파티셔닝으로 무기한 수용(`ingest_time`으로 지연 관측) — lateness 폐기 없음 |
| 무손실 보존 | 파싱 실패 레코드 Dead-Letter Queue 격리 |
| 스키마 진화 | Iceberg table format으로 하위호환 변경 |
| 데이터 품질 | dbt 테스트로 규칙 위반 행 저장·추적 |
| 로컬 테스트성 | Kafka·Flink·ES·Iceberg 컨테이너 E2E + BigQuery는 Sandbox/DuckDB(dbt-duckdb)/bigquery-emulator |
| 부하 검증 | 가설-우선 부하 테스트(목표 RPS·p99 SLO 선정 후 측정·비교) |

## 프로젝트 구조

```
FleetSentinel/
├── ingestion/        # (Python) 텔레메트리 생성기 / SUMO·리플레이 → Kafka
├── pipeline/         # (Java, Flink) Flink 스트림 처리 (Bronze/Silver)
├── transform/        # (SQL, dbt) Silver(Iceberg) → Gold(BigQuery), BQ ML 이상탐지, 데이터 품질 테스트
├── orchestration/    # (Python, Airflow) DAG — 로컬 Airflow / 세션 시 GKE in-cluster
├── serving/          # Elasticsearch 매핑 / Kibana 대시보드·Alerting
├── schemas/          # Avro 정본 스키마 (telemetry-event.avsc, dlq-envelope.avsc — SDD §6.1)
├── infra/            # Terraform (GCP), Docker, CI
└── docs/             # 아키텍처·스키마·의사결정 (sdd.md 등)
```

## 로드맵

구현은 5단계(수집 → 정제 → 집계 → 서빙 → 부하·검증)로 진행합니다. 단계별 범위·환경·완료 기준은 [SDD §16 Rollout Plan](docs/sdd.md)에 정리돼 있습니다.

## 결과 (측정 예정)

> 아래 수치는 실제 구현·측정 후 채웁니다. (검증되지 않은 숫자는 기재하지 않습니다.)

| 지표 | 값 |
|---|---|
| 피크 처리량 (RPS) | _(측정 예정)_ |
| 누적 처리 이벤트 수 | _(측정 예정)_ |
| p95 / p99 지연 | _(측정 예정)_ |
| 유실률 / 중복률 | _(측정 예정)_ |
| Gold 집계 대비 원본 압축비 | _(측정 예정)_ |

## 문서

- [System Design Document (SDD)](docs/sdd.md)

## 라이선스

본 프로젝트는 [MIT License](LICENSE)로 배포됩니다.
