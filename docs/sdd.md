# FleetSentinel — Software Design Document

> ⚠️ **v3.0 전환 안내.** 본 문서는 **v2.0(차량 OBD 텔레메트리)** 설계다. 프로젝트가 자율주행
> 멀티모달 도메인으로 전환하면서 **§6 Data Design은 [`data-design-v3.md`](data-design-v3.md)로 대체**됐다.
> §5 아키텍처·§7 컴포넌트·§16 롤아웃도 개정 대상이다. 두 문서가 충돌하면 v3 문서가 우선한다.
> 인프라 계층(§4.1.1 버전 매트릭스, ADR-002/005/006/009)과 ADR 근거는 그대로 유효하다.


> 본 문서는 [sysdesign-challenges SDD 템플릿](https://github.com/lsh1215/sysdesign-challenges/blob/main/templates/System-Design-Document/software-design-document-style.md)(IEEE 1016 기반)을 FleetSentinel에 맞춰 작성한 것이다. **모든 설계 값은 확정되었다.** 유일한 placeholder는 **저자·리뷰어·리비전 Author·리스크 Owner(§13) 칸**의 `{이름}`뿐이다. 성능 수치(G-2/G-3, §9)는 목표치이며 실측 검증은 §15 부하시험에서 수행한다. 문서 렌더링·앵커 슬러그는 GitHub 기준.

---

## 0. Document Metadata

| 항목 | 값 |
|---|---|
| Document Title | FleetSentinel SDD |
| Version | 2.0 |
| Status | **Reviewed — v2.0 확정.** v1.0(Pub/Sub+Dataflow 관리형) → v2.0(Kafka+Flink+Iceberg+ES 자체호스팅) 전면 개정. critic+architect 2라운드 검토 지적(F1~F14) 전량 반영 후 architect 최종 확인 3×CLEAR·APPROVE(blocker 0). 검토 산출물: `design-review/v2-review-fixes.md` |
| Author(s) | {이름} |
| Reviewer(s) | {이름} |
| Last Updated | 2026-07-22 |
| Related Documents | [README](../README.md), [호스팅·이상탐지 결정 리서치](design-review/hosting-and-ml-decisions.md), [v2 개정 계약](design-review/v2-revision-contract.md), Prior art: [AutoNotify](https://github.com/Qualcomm-Capstone) |

### 0.1 Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-21 | {이름} | Initial draft |
| 0.2 | 2026-07-21 | {이름} | §6 Data Design 강화: polyglot 저장소 전략(§6.5)·지오 처리(§6.6)·Data Dictionary 확장·ADR-004 추가 |
| 0.3 | 2026-07-21 | {이름} | §6 파이프라인 상세 설계(G002): 직렬화 포맷(Avro) 확정·ADR-008, 처리 의미론(§6.4.1 exactly-once·dedup·late data), DLQ 설계(§6.7), 계층별 저장 설계(§6.8: Bronze 파티션·Silver/Gold DDL·ES 매핑/보존정책), dbt/Airflow 상세(§7.3/§7.4), Messaging/Internal Interfaces 갱신(§8) |
| 0.4 | 2026-07-21 | {이름} | G003 기술 스택·열린 결정 전량 해소: §12 Alternatives Considered 계층별 확장(스트림 엔진/수집/Bronze 포맷/서빙/변환/오케스트레이션), ADR-009(오케스트레이션 하이브리드 운영 모델) 신설, comma2k19 기각 확정(§1.3·§13 R-2, README 반영), Cloud SQL/CDC를 Phase 3 확장 트랙으로 확정(§4.1·§6.5·§16), Bronze/Silver/Gold 보존정책 확정(§6.3), NFR 목표치 확정(§9), GCP 비용 추정 신설(§9.1), Capacity 추정 실체화(§18 B), §14 Traceability 실명화, §18 Open Questions 0건 |
| 1.0 | 2026-07-22 | {이름} | G004 5레인 초검토 반영·v1.0 확정: gemini 외부 리뷰(BQ 비동기 백필 `dlq/bq/`·Streaming Engine 과금 수치·§10.5 CI/CD·§10.2 대시보드 청사진·effectively exactly-once 용어·ADR-009 상태 비공유), critic(§16.1 5-Phase 정본+P1-P2 로컬 실행 스펙·dim_vehicle seed 확정+side-input 계약·§15 LT-LOAD-01 측정 프로토콜+TC-RECON-01 대사·§8.1 Pub/Sub 스키마 운영 계약·관측성 Cloud Monitoring 기본 축소·SINK_WRITE_FAILURE 분류), cartesian-doubt(TC-ULID-01 신설·비용 기초 가정 명시), first-principles(재도출 감사 통과), architect(§6.7 error_class별 재처리 분기·backfill 소스 확정·§14 G-4/G-5 행) — 발견 30건 전량 반영, blocker/major 잔존 0 |
| 2.0 | 2026-07-22 | {이름} | **전면 개정: v1.0(Pub/Sub+Dataflow 관리형) → v2.0(자체호스팅 OSS 스트리밍 레이크하우스: Kafka+Flink+Iceberg+Elasticsearch)**. 수집=Kafka(KRaft self-host, 3-broker 단일호스트, RF=3/ISR=2, ADR-002/ADR-009), 처리=네이티브 Flink(Dataflow/Beam 제거, DataStream+SQL, exactly-once=체크포인트+오프셋+2PC, ADR-005/ADR-006), 저장=Iceberg 중심(Bronze+Silver=Iceberg, Gold=BigQuery via BigLake, ADR-003), 서빙=Elasticsearch self-host(Basic tier), 이상탐지=BigQuery ML(Elastic ML 드롭, ADR-010), 인프라=GKE/GCE 자체호스팅(ADR-007, §9.1 node-hours 재산정), 로컬 테스트=Kafka→Flink→Iceberg→ES 전 구간 + BigQuery는 DuckDB(dbt-duckdb)/bigquery-emulator/Sandbox 3층 대체(ADR-011). ADR-001~011 전면 재편, §5/§6/§7/§9.1/§12/§13/§15/§16 갱신. 근거: [v2 개정 계약](design-review/v2-revision-contract.md), [호스팅·이상탐지 리서치](design-review/hosting-and-ml-decisions.md). |
| 2.0.1 | 2026-07-22 | {이름} | v2.0 리뷰 통합 수정([v2-review-fixes.md](design-review/v2-review-fixes.md)) 반영해 v2.0 확정: **GROUP A(F1~F13)는 본 문서**, **GROUP B(F14a/b)는 `schemas/*.avsc` doc + README 2본**에 반영. dim_vehicle enrich를 GCS fleet CSV 단일 경로로 통일(F1), BigLake 인용을 read-only 외부테이블 정본으로 교체 + 카탈로그를 BigLake metastore(Iceberg REST catalog)로 구체화(F2), Airflow를 로컬/세션 시 GKE in-cluster로 명시(F3), TC-RECON-01 항등식 정의(F4), G-4/이상탐지 스트레치(P5) 게이트 + `unique` `severity=warn` + 차단/탐지 분리(F5), §4.1.1 버전 매트릭스 신설(Flink 2.0.x/Iceberg 1.11.x/Kafka 4.x/ES 8.x, F6), `iceberg_maintenance` DAG + §6.3 정정(F7), upsert 파티션 스코프 equality delete 한계(F8), DAG 표 MVP/스트레치 열(F9), Kafka 스키마 핀 고정(F10), §0 안내문 리스크 Owner 칸(F11), §11 ADR re-baseline 주석·매핑(F12), 텍스트 다이어그램 v2.0 정본 명시+PNG P1전 백로그(F13). architect 최종 확인 APPROVE(3×CLEAR). |

---

## 1. Introduction

### 1.1 Purpose
본 문서는 **FleetSentinel** — 차량 fleet 규모의 실시간 텔레메트리를 수집·정제·분석하는 데이터 엔지니어링 플랫폼 — 의 설계를 기술한다. 대상 독자는 데이터 엔지니어(구현자), 리뷰어, 채용 담당자(포트폴리오 심사)다. 본 프로젝트는 Qualcomm 기업 연계 캡스톤 **AutoNotify**(엣지→MQTT 이벤트 기반 과속탐지·알림)를 개인적으로 확장한 것으로, 단일 차량 이벤트 처리를 fleet 규모 연속 텔레메트리 데이터 플랫폼으로 일반화한다.

### 1.2 Scope
- **In scope**: 텔레메트리 수집(ingestion, **자체호스팅 Kafka**), 스트림 처리(Bronze/Silver, **자체호스팅 Apache Flink + Apache Iceberg 오픈포맷 레이크**), 배치 변환/집계(Gold, BigQuery), 데이터 품질, 실시간 서빙(**자체호스팅 Elasticsearch**/Kibana), 관측성. 전체 스택을 **자체호스팅 OSS 스트리밍 레이크하우스**(Kafka+Flink+Iceberg+ES)로 구성해 GCP 관리형 서비스 의존을 스트림 코어에서 제거하고, 인프라(GKE/GCE)·오픈소스 운영 역량 시그널을 확보한다(§5.1).
- **Out of scope**: 실제 차량 하드웨어/펌웨어, 대시보드 프론트엔드 UI 구현 세부, 프로덕션 규모 멀티리전 운영.

### 1.3 References
- [README](../README.md)
- Prior art: [AutoNotify (Qualcomm 기업 연계 캡스톤)](https://github.com/Qualcomm-Capstone)
- 데이터셋: [Kaggle Levin OBD-II 차량 텔레메트리](https://www.kaggle.com/datasets/yunlevin/levin-vehicle-telematics)(실측 분포 보정용, 선택); 시뮬레이터: SUMO/TraCI(LuST 시나리오). comma2k19는 검토 후 기각(§13 R-2 근거).
- v2.0 전환 근거: [v2 개정 계약](design-review/v2-revision-contract.md), [호스팅·이상탐지 결정 리서치](design-review/hosting-and-ml-decisions.md).

---

## 2. System Overview

FleetSentinel은 다수 차량이 실시간으로 쏘는 텔레메트리(속도·위치·RPM 등)를 **자체호스팅 Apache Kafka**로 수집해, **자체호스팅 Apache Flink**가 **Medallion(Bronze/Silver/Gold)** 으로 정제하고, 오픈포맷 레이크(**Apache Iceberg**)·분석 웨어하우스(**BigQuery**, Gold)·실시간 서빙 엔진(**Elasticsearch**)에 동시에 적재한다. 핵심은 **"단일 Flink 잡, 다중 싱크"** — 하나의 Flink 스트리밍 잡이 같은 스트림을 ①원본 보존(Iceberg Bronze) ②정제 데이터(Iceberg Silver) ③실시간 서빙(ES)으로 분리 적재하고(§5.2), Silver 위에서 dbt가 **BigLake 외부테이블**로 Gold(BigQuery)를 배치 생성한다.

```
┌─ External ─────────────┐   ┌─ FleetSentinel ────────────────────┐   ┌─ Consumers ──────────┐
│ 차량 텔레메트리 소스     │ → │ Kafka 수집 → Flink 정제(Medallion)   │ → │ 분석가 / 대시보드 /    │
│ (SUMO 시뮬 / 리플레이)   │   │ → Iceberg(Bronze/Silver) →          │   │ 이상탐지 알림          │
│                        │   │   BigQuery(Gold, BQ ML) + ES(실시간) │   │                       │
└────────────────────────┘   └─────────────────────────────────────┘   └──────────────────────┘
```

---

## 3. Goals and Non-Goals

### 3.1 Goals
- **G-1**: fleet 규모 스트림을 **무손실 + effectively exactly-once**로 정제 — 유실 0, 중복은 dedup TTL 내 보장 + TTL 밖 잔존 중복은 스테이징 dedup·dbt 게이트로 차단(§6.4.1). "effectively"는 이론적 한계(TTL 밖 경로)를 명시한 정직한 한정어다.
- **G-2**: 초당 **5,000 rps sustained**, 6시간 부하시험 기준 누적 **1억+ 건**(5,000 rps × 6h ≈ 1.08억 건) 처리 — 목표치이며 실측 검증은 §15 부하시험에서 수행한다.
- **G-3**: 실시간 서빙 지연 **p99 < 300ms**(Kibana/ES 검색 기준) — 목표치이며 실측 검증은 §15 부하시험에서 수행한다.
- **G-4**: 원본→Gold 정제 과정이 **데이터 품질 게이트**(dbt 테스트)로 검증됨.
- **G-5**: "피드백 → 설계 대응" 추적 가능성 확보(포트폴리오 서사).

### 3.2 Non-Goals
- **NG-1**: 실제 차량/엣지 하드웨어 연동 — 시뮬레이터·리플레이로 대체.
- **NG-2**: 멀티리전 active-active — 단일 리전으로 시작.
- **NG-3**: 자체 ML 모델 학습(모델 아키텍처 설계·학습 파이프라인 자체 구축) — **BigQuery ML**(`ML.DETECT_ANOMALIES`/`ARIMA_PLUS`, ADR-010) 등 SQL-native 관리형 이상탐지 우선. Elastic ML은 self-host Basic tier에 미포함이라 드롭(§4.1, 호스팅 리서치 §2).

---

## 4. Constraints

### 4.1 Technical Constraints — 기술 스택 (하이브리드)

클라우드는 **GCP(인프라)** 위에 **자체호스팅 OSS 스트리밍 레이크하우스**를 얹고, 언어는 **역할 분리형 하이브리드**를 채택한다 (근거: [ADR-001](#adr-001-하이브리드-언어-전략-javaflink--pythonsql-글루)).

| 계층 | 기술 | 언어 |
|---|---|---|
| 수집(Ingest) | **Apache Kafka self-host**(KRaft, ZooKeeper 없음, 공식 `apache/kafka` 이미지, 단일 호스트 3-broker StatefulSet/compose, [ADR-002](#adr-002-수집--apache-kafka-self-host-vs-pubsub)·[ADR-009](#adr-009-kafka-ha-범위--broker-level-복제failover-vs-인프라-ha)) | — |
| 텔레메트리 생성기 | SUMO(TraCI, LuST 시나리오) — Kaggle Levin OBD-II 실측 분포 보정(선택, §7.1) | **Python** |
| **스트림 처리 코어**(Bronze/Silver) | **네이티브 Apache Flink self-host**(JobManager+TaskManager, RocksDB state backend) — 체크포인트 exactly-once·`keyBy` dedup·enrich·DLQ, DataStream + Flink SQL | **Java** |
| Bronze 저장 | **GCS + Apache Iceberg**(Flink 네이티브 Iceberg 싱크) | — |
| Silver 저장 | **GCS + Apache Iceberg**(Flink 네이티브 Iceberg 싱크) — v1.0의 "Silver=BigQuery"에서 변경 | — |
| Gold 저장 | **BigQuery** — dbt가 **BigLake 외부테이블**로 Silver Iceberg를 조회해 생성 | — |
| (Phase 3 확장) 관계형 메타/CDC | **Cloud SQL**(PostgreSQL) — 차량 레지스트리 dim·멱등성 inbox, Debezium CDC·아웃박스 데모(코어 완료 후, §16) | — |
| 변환(Silver→Gold) | **dbt**(BigLake 외부테이블 경유, 변환 + 데이터 품질 테스트) | **SQL** (+ Python config) |
| 오케스트레이션 | **Airflow** — 로컬 Docker Compose(개발·일상, Flink 잡 제출도 트리거 가능) | **Python** |
| 실시간 서빙 | **Elasticsearch self-host**(Docker/GKE, 무료 **Basic tier**) · Kibana(Maps, Alerting) | — |
| 이상탐지 | **BigQuery ML**(`ML.DETECT_ANOMALIES`, `ARIMA_PLUS`, Gold 대상) + Kibana 규칙 알림(Basic) — Elastic ML 드롭([ADR-010](#adr-010-이상탐지--bigquery-ml-vs-elastic-ml)) | — |
| 관측성 | **Cloud Monitoring/Logging(기본, 관리형 — GKE/GCE·BigQuery 지표)** + Prometheus·Grafana·Loki(로컬 개발 한정, Kafka/Flink JMX·Iceberg 메트릭 포함 — §10.2) | — |
| 인프라 | **GKE(권장) 또는 GCE self-host**(Kafka+Flink+ES) — 1st-party 컴퓨트로 크레딧 커버([ADR-007](#adr-007-인프라--gkegce-자체호스팅-vs-완전관리형)) | — |
| IaC / CI | **Terraform** · Docker · GitHub Actions | — |

> 언어 요약: **Java(고throughput 스트림 코어, Flink) + Python(글루·오케스트레이션) + SQL(변환)**. AutoNotify에서 검증한 이벤트 기반·DLQ·idempotency 규율을 재사용한다.


### 4.1.1 버전 매트릭스 (Flink/Iceberg/Kafka/ES 호환, 로컬=prod 동일 버전)

| 컴포넌트 | 버전 | 근거 |
|---|---|---|
| Apache Flink | **2.0.x**(DataStream + SQL) | Iceberg·Kafka·Elasticsearch 커넥터가 동시에 GA로 지원하는 최신 라인 — 2.1.x 이상은 아래 ES 커넥터가 아직 릴리스되지 않음([Apache Flink Downloads](https://flink.apache.org/downloads/)) |
| Apache Iceberg | **1.11.x**(`iceberg-flink-runtime-2.0`) | Flink 2.0 런타임 jar가 정식 배포됨([Apache Iceberg 1.11.0 Release](https://iceberg.apache.org/releases/)), format-version 2(row-level delete) |
| flink-connector-kafka | **4.0.1** | Flink 2.0.x 호환 공식 릴리스([Apache Flink Downloads](https://flink.apache.org/downloads/)) |
| flink-connector-elasticsearch | **4.0.0**(`flink-connector-elasticsearch8`) | Flink 2.0.x 호환 + ES 8.x `Elasticsearch8AsyncSinkBuilder` 지원 — Flink 2.1 이상은 아직 ES 커넥터 릴리스가 없음([Elasticsearch Connector — Apache Flink 2.0](https://nightlies.apache.org/flink/flink-docs-release-2.0/docs/connectors/datastream/elasticsearch/)) |
| Kafka 브로커(`apache/kafka` 이미지) | **4.x**(KRaft 필수, ZooKeeper 완전 제거) | [Apache Kafka Downloads](https://kafka.apache.org/downloads/) — 4.0부터 KRaft-only(§4.1 기존 결정과 정합) |
| Elasticsearch | **8.x**(self-host, Basic tier) | 위 Flink 커넥터의 GA 지원 버전과 정합, Basic tier 무료 정책 변경 없음(§5.3) |
| State backend | RocksDB(Flink 내장) | Flink 배포에 포함, 별도 버전 핀 불요 |

- 로컬(§16.1)·prod 동일 버전을 사용한다 — 로컬 Flink MiniCluster·docker-compose Kafka·Docker Elasticsearch 모두 위 버전으로 고정.
- **커넥터 호환이 좁은 이유**: Iceberg flink-runtime과 flink-connector-kafka는 Flink 2.1까지 앞서가지만, flink-connector-elasticsearch는 아직 Flink 2.0.x 릴리스만 존재해 ES 싱크가 병목이다 — 전체 스택은 **가장 뒤처진 커넥터(ES) 기준**으로 Flink 2.0.x에 고정한다(검증 시점 2026-07-22 기준, 커넥터 신규 릴리스 시 재검토).

### 4.2 Organizational / Business Constraints
- 1인 개인 프로젝트(포트폴리오) — 스코프는 코어 파이프라인에 집중, 과설계 지양.
- 예산: 개인 GCP 크레딧 한도 내 — 비용 최적화(자체호스팅 컴퓨트 = 1st-party 크레딧 커버, 캠페인 stop/start) 고려. Confluent Cloud·Elastic Cloud 등 3rd-party Marketplace는 무료 크레딧 미적용이라([GCP 무료 크레딧 제한](https://docs.cloud.google.com/free/docs/free-cloud-features)) self-host를 기본으로 한다(호스팅 리서치 §서두).

### 4.3 Regulatory / Compliance Constraints
- 실제 개인식별 차량 데이터 미사용(시뮬/공개 데이터) — PII 규제 부담 낮음. 실데이터 확장 시 위치정보 처리 정책 재검토.

---

## 5. System Architecture

### 5.1 Architectural Style

**Kappa 기반 스트리밍 파이프라인 + 자체호스팅 스트리밍 레이크하우스(Kafka+Flink+Iceberg) + Medallion.** 수집·정제는 스트림 단일 경로(Kappa, Kafka→Flink), 집계(Silver→Gold)는 배치(dbt via BigLake)로 수행한다.

| 스타일 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **Lambda** (배치+스트림 이중 경로) | 배치 정확성 + 스트림 신선도 | **같은 정제 로직을 2번 구현·유지**(코드 이중화, 결과 불일치 위험) | ❌ 기각 |
| **Kappa** (스트림 단일 경로) | 정제 로직 1벌, 재처리는 로그 리플레이 | 대규모 히스토리 재연산에 스트림 엔진 비용 | ✅ **수집·정제 채택** |
| 순수 배치 (Medallion-only) | 단순·저비용 | 실시간 이상탐지·지도 불가(G-3 위배) | ❌ 기각 |

- 근거: Lambda의 본질적 문제는 "동일 로직의 이중 구현"이다(Kreps, [Questioning the Lambda Architecture](https://www.oreilly.com/radar/questioning-the-lambda-architecture/), O'Reilly 2014). FleetSentinel은 **정제(스트림)와 집계(배치)가 서로 다른 로직**이라 이중 구현이 없다 — Kappa의 단일 정제 경로 + dbt 배치 집계는 Lambda가 아니라 역할 분담이다.
- 재처리(Kappa의 코어 요구): Bronze(Iceberg)가 리플레이 소스 — 정제 로직 변경 시 Bronze→Silver **Flink batch 모드 재실행**(동일 코드). Kafka `telemetry.raw` retention(운영 값은 §8.1)은 단기 재소비용.
- **자체호스팅 레이크하우스로 전환한 이유**: 관리형(Pub/Sub+Dataflow)은 서버리스 운영 부담이 낮은 대신 스트림 엔진 자체를 소유·튜닝하는 시그널이 없다. Kafka(코어 수집 표준)·Flink(고성능 상태 기반 스트림 처리 표준)·Iceberg(오픈 테이블 포맷 표준)로 전환해 "자체 운영 스트리밍 인프라" 역량을 직접 증명한다([ADR-005](#adr-005-처리--네이티브-apache-flink-vs-dataflowspark) 근거).
- 상세: [ADR-005](#adr-005-처리--네이티브-apache-flink-vs-dataflowspark).

### 5.2 Component Diagram

![System Architecture](diagrams/system-architecture.png)

> ⚠️ **아래 텍스트 다이어그램(본 절 하단 `<details>`)이 v2.0 정본이다.** 위 PNG는 구버전 토폴로지를 반영할 수 있어 텍스트 다이어그램·컴포넌트 표와 불일치할 수 있다 — PNG 재생성은 **P1 착수 전 백로그**(§16.1)로 남아 있다.

> 편집 가능한 원본: [`diagrams/system-architecture.excalidraw`](diagrams/system-architecture.excalidraw) (Excalidraw)

**컴포넌트 책임·인터페이스:**

| 컴포넌트 | 책임 | 입력 → 출력 | 장애 시(§5.4) |
|---|---|---|---|
| Telemetry Generator (Python) | SUMO/TraCI 시뮬 → 이벤트 생성·발행 | SUMO 시나리오 → Kafka `telemetry.raw` | 데이터 공급만 중단 |
| **Kafka**(self-host, KRaft, 단일호스트 3-broker) | 수집 버퍼(at-least-once, RF=3/ISR=2) | producer → consumer group | broker 1개 kill까지 무손실(§5.4, ADR-009) |
| **Flink Stream Processor**(JobManager+TaskManager, Java, **단일 잡**) | `keyBy(event_id)` dedup→검증→enrich→**다중 싱크** | Kafka → ①Iceberg Bronze(raw) ②Iceberg Silver ③ES(실시간) + DLQ | 체크포인트 재시작(§5.4) |
| dbt (SQL, BigLake 경유) | Silver(Iceberg)→Gold(BigQuery) 변환+품질 테스트 | BigLake 외부테이블(Silver Iceberg) → BigQuery Gold | 재실행 멱등 |
| Airflow (로컬 Docker Compose / 세션 시 GKE in-cluster, §5.3) | dbt·백필·BQ ML·ES 보존 스케줄, Flink 잡 제출 트리거 | cron/센서 → dbt, Flink batch | 배치 지연만 |
| Elasticsearch + Kibana (self-host, Basic tier) | 실시간 검색·Maps·규칙 알림 | ES index → 대시보드 | 유실 0, 지속 장애 시 지연 전파 가능(§5.4, R-4) |

**잡 구성 결정 — 단일 Flink 스트리밍 잡 (Bronze/Silver 분리 잡 기각):**
- 근거: self-host Flink 클러스터는 TaskManager 상시 가동이 비용을 지배한다(§9.1). 단일 Flink DAG 안에서 분기(raw→Iceberg Bronze, validated→Iceberg Silver/ES)하면 클러스터 1개로 지연 최소·운영 단순. Bronze 재처리 독립성은 분리 클러스터가 아니라 **필요 시 기동하는 batch 모드 잡**(동일 코드)으로 확보.
- Bronze/Silver 싱크 커넥터: **Flink Iceberg 싱크**(`FlinkSink`, DataStream API) — 체크포인트 완료 시점에 Iceberg 스냅샷을 원자적으로 커밋한다([Flink Connector — Apache Iceberg](https://iceberg.apache.org/docs/latest/flink-connector/)). 커밋 주기는 체크포인트 간격(§6.4.1)에 연동.

**ES 싱크 경로 결정 — Flink 잡 내 Elasticsearch 커넥터 직접 write:**

| 대안 | 평가 | 판정 |
|---|---|---|
| **Flink 잡에 [Elasticsearch 커넥터](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/elasticsearch/) 싱크 추가** | 클러스터 1개(비용↓), `doc_id=event_id` 멱등 upsert, geo_point 매핑·인덱스 완전 제어 | ✅ **채택** |
| 별도 색인 서비스(Logstash/커스텀 컨슈머) | VM/컨테이너 상시 운영 부담 추가, exactly-once 아님 | ❌ |

- ES는 트랜잭션 싱크가 아니므로 exactly-once는 **`doc_id=event_id` 멱등 색인**으로 달성(재시도 시 덮어쓰기 = 중복 0; event_id 발급 계약은 §6.2). 인덱스 매핑(geo_point)·보존정책은 사전 생성 index template + delete-by-query로 제어(§6.6·§6.8).
- **ES write 실패 처리**: 재시도 상한 초과·매핑 충돌·bulk reject 문서는 Elasticsearch 커넥터 error output으로 빼서 **ES 전용 DLQ**(GCS `dlq/es/`)에 격리 — ES 지연으로 인한 잡 정체를 **재시도 상한 내로 bound**하고(§5.4·R-4와 상보), 복구 후 DLQ에서 재색인.
- **Iceberg 싱크 실패 처리**: 체크포인트 커밋 실패(카탈로그 불가·GCS 쓰기 실패 등)는 Flink 체크포인트 자체가 실패해 잡이 마지막 성공 체크포인트로 롤백·재시도한다(§6.4.1) — 별도 shed 없이 **잡 레벨 재시도**가 1차 방어선이며, 재시도 상한을 넘는 지속 장애만 운영자 개입(§5.4).
- **Gold→ES 집계 경로**: 실시간 아님 → Gold(BigQuery) 배치 export를 Airflow가 스케줄(§7.4).
- 상세: [ADR-006](#adr-006-exactly-once--flink-체크포인트--kafka-오프셋--iceberg-2pc--es-멱등).

<details>
<summary>텍스트 다이어그램 (상세)</summary>

```
[SUMO+LuST 생성기 (Python, TraCI)]  key=vehicle_id, WGS84 변환 후 publish
        ▼
   Kafka `telemetry.raw` (self-host KRaft, RF=3/ISR=2, 단일호스트 3-broker)
        ▼
 ┌─ Flink Stream Processor — self-host(JobManager+TaskManager) 단일 잡 ─┐
 │  event_id(ULID) keyBy dedup [상태 TTL 30분] → 스키마 검증(실패→DLQ)   │
 │  → 차량 메타 enrich(집계 윈도우 없음, §6.4.1)                        │
 │  → 다중 싱크(체크포인트 완료 시 원자 커밋):                          │
 │     ① Bronze: GCS+Iceberg (raw 무손실, Flink Iceberg 싱크)          │
 │     ② Silver: GCS+Iceberg (정제, Flink Iceberg 싱크)                │
 │     ③ ES: Elasticsearch 커넥터, doc_id=event_id 멱등 upsert (실시간) │
 └───────────────────────────────────────────────────────────────────┘
        ▼ (배치, BigLake 경유)              ▼ (실시간 서빙)
  Silver(Iceberg) ─ dbt(SQL) ─▶ Gold(BigQuery)   Elasticsearch (geo_point)
        │  Airflow(로컬 Docker Compose / 세션 시 GKE in-cluster) 스케줄 ├ Kibana Maps(실시간 지도)
        ▼                                        ├ BigQuery ML(이상탐지)
  Gold ──(BQ 배치 export)──▶ ES                   └ Kibana Alerting(임계 알림)
  (재처리: Bronze 리플레이 = 동일 Flink 코드 batch 모드)
```

</details>

### 5.3 Deployment Topology

| 항목 | 결정 | 근거 |
|---|---|---|
| Region | **`asia-northeast3`(서울) 단일 리전 + multi-zone** | 사용자 근접(지연), GKE/GCE·BigQuery·Cloud Run 전부 제공([GCP locations](https://cloud.google.com/about/locations)). 멀티리전은 NG-2 |
| Kafka 클러스터 | **self-host** — GKE `StatefulSet replicas: 3`(권장) 또는 GCE VM 1대에 docker-compose 3컨테이너. **단일 호스트에 브로커 3개**, KRaft(ZK 없음), Strimzi 미사용(오퍼레이터 불필요, ecommerce-microservices 선례 재활용) | 자체운영 스트리밍 시그널 확보, 크레딧 커버(1st-party 컴퓨트, ADR-002·ADR-009) |
| Flink 클러스터 | **self-host** — GKE Deployment: JobManager 1 + TaskManager N(오토스케일 대신 고정 N, RocksDB state backend), 체크포인트 저장소 = **GCS**(`gs://.../checkpoints`) | 체크포인트를 durable object storage에 두어 TaskManager/Pod 재기동에도 상태 복구(§5.4·§6.4.1, [Checkpointing — Apache Flink](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/checkpointing/)) |
| Elasticsearch | **self-host**(Docker 로컬 / GKE StatefulSet), **Basic tier**(무료) | Kibana Maps·Alerting 포함, 라이선스 비용 0. Elastic Cloud(관리형)는 elastic.co 직접가입 14일 trial로 곁들이기만 — GCP Marketplace 경유는 trial 미적용([Elastic Pricing FAQ](https://www.elastic.co/pricing/faq), 호스팅 리서치 §1) |
| 생성기 런타임 | 개발·데모=**로컬(Mac, sumo-gui)** / 부하시험=**Cloud Run Jobs**(headless, 시간가속) | 데모 서사는 로컬 sumo-gui→Kibana. 부하는 [Cloud Run Jobs](https://cloud.google.com/run/docs/create-jobs)(최대 24h, 서버리스)로 시간가속 실행 — Kafka/Flink/ES 클러스터 운영과 별개로 생성기만 서버리스 유지(§7.1) |
| 오케스트레이션(Airflow) | **로컬 Docker Compose**(개발·일상) / **세션 시 GKE in-cluster**(Kafka/Flink/ES와 동일 노드군, §12.7) — 로컬 개발에서 클라우드 세션의 Flink REST API·ES에 접근할 때는 `kubectl port-forward`로 터널링 | self-host 통일로 크레딧 절약·운영 일관성(§12.7) — Composer 세션형 하이브리드(v1.0) 대비 단순화 |
| Network | 커스텀 VPC 1개, GKE/GCE 워커 **내부 IP 전용** + [Private Google Access](https://cloud.google.com/vpc/docs/configure-private-google-access) 서브넷 | 외부 IP 제거(보안·비용). Kafka/Flink/ES는 클러스터 내부 통신, 외부 노출 없음 |
| Secrets | Secret Manager(BigQuery/GCS 서비스 계정 키, ES 관리 자격) | 코드·설정에 평문 금지 |

**IAM 서비스 계정 (최소 권한):**

| SA | 역할 | 근거 |
|---|---|---|
| `sa-generator` | Kafka producer(ACL, topic 한정) | publish만 |
| `sa-flink` | `storage.objectAdmin`(bronze/silver/checkpoint 버킷 한정), `bigquery`는 불필요(Flink는 BQ를 읽지도 쓰지도 않음 — enrich는 GCS fleet CSV 로드, §7.2) | 코어 잡 필요 권한만 — v1.0 대비 BQ 권한 제거(§4.1) |
| `sa-dbt` | `bigquery.dataEditor`(gold 한정) + `bigquery.connectionUser`(BigLake 연결) | Silver Iceberg를 BigLake로 읽어 Gold 적재 |
| `sa-airflow` | Flink REST API 잡 제출 권한, `bigquery.jobUser`+`dataEditor`(gold 한정) | 오케스트레이션 |
| 사람(개발자) | 콘솔 Viewer + 필요 시 임시 상승 | 상시 Owner 금지 |

### 5.4 Failure Domains & Recovery Paths

| 장애 | 데이터 영향 | 복구 경로 |
|---|---|---|
| 생성기 다운 | 신규 데이터만 중단(파이프라인 무손상) | 재시작. 시뮬 재개 |
| **Kafka 브로커 1개 kill** | RF=3/ISR=2라 무손실(§4.1, ADR-009) | 컨트롤러 재선출·파티션 리더 재선출, producer/consumer 자동 재접속. 데모 시연 대상 |
| Kafka 브로커 2개 이상 동시 손실 | ISR<min.insync.replicas(2) → write 거부(가용성 저하, 유실은 없음) | 브로커 재기동으로 쿼럼 복구 — **인프라 HA(존/호스트 SPOF) 대응은 스코프 밖**(정직한 프레이밍, ADR-009) |
| **Flink TaskManager/Pod 장애** | 체크포인트 완료분까지 무손실 | JobManager가 실패한 태스크를 재스케줄, **마지막 성공 체크포인트에서 상태 복구**(Kafka 오프셋 재탐색 포함, [Fault Tolerance — Apache Flink](https://nightlies.apache.org/flink/flink-docs-stable/docs/learn-flink/fault_tolerance/)) |
| **Flink JobManager 장애** | 체크포인트 메타데이터는 GCS에 durable — HA 미구성 시 잡 재기동 필요(단일 개발 클러스터, HA JobManager는 스코프 밖) | 재기동 시 최신 체크포인트에서 재개, 재전달 중복은 keyBy dedup이 제거 |
| 스키마 불량 메시지 | 정상 흐름 오염 없음 | DLQ `telemetry.dlq` 격리 → 수정 후 리플레이(§6) |
| **Iceberg 싱크 커밋 실패**(GCS/카탈로그 불가) | 체크포인트 실패 → 잡이 마지막 성공 체크포인트로 롤백·재처리, 워터마크 정체 가능 | 체크포인트 재시도(§6.4.1). 지속 장애 시 잡 정체가 ES 싱크도 동반 저하시킬 수 있음(단일 잡 fan-out, R-4) — 백로그·체크포인트 지연 알림(§10.2)으로 조기 탐지 |
| ES 장애 | **유실 0**(정본 무손상)이나, in-job 싱크라 **지속 장애 시 잡 전체 지연 전파 가능(R-4)** | 재시도 상한 초과 문서는 ES DLQ로 shed(§5.2) → 잡 정체 방지. 복구 후 재색인: Bronze/Silver Iceberg→ES 재구성(ADR-004). doc_id 멱등이라 안전 |
| Airflow 장애 | Gold 갱신·보존 집행 지연만 | DAG 재실행(dbt 멱등, delete-by-query 멱등) |
| 리전 장애 | 전체 중단(NG-2 수용) | 단일 리전 한계 명시 — IaC(Terraform)로 타 리전 재프로비저닝 |

---

## 6. Data Design

### 6.1 Data Model
텔레메트리 이벤트의 **정본 스키마는 Avro**(`schemas/telemetry-event.avsc`, namespace `io.fleetsentinel.telemetry.v1`, record `TelemetryEvent`)로 고정한다. 필드는 아래 §6.2 Data Dictionary와 완전히 일치한다. DLQ 봉투 스키마는 `schemas/dlq-envelope.avsc`(§6.7). **v2.0에서도 Avro 스키마·필드 정의는 변경 없음** — 전송 계층이 Pub/Sub→Kafka로 바뀔 뿐 페이로드 계약은 동일.

**직렬화 포맷 결정 — Avro(binary) 채택 (Protobuf·JSON 기각):**

| 포맷 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **Avro (binary)** | Kafka 생태계 표준 직렬화(Confluent/OSS Schema Registry 선택 가능), DE 생태계(Iceberg/Flink/BigQuery) 표준·커넥터 친화 | 코드젠 생태계가 Protobuf보다 얇음(단, Java/Python 표준 Avro 라이브러리로 충분) | ✅ **채택** |
| Protobuf | 컴팩트, Kafka에서도 사용 가능 | 분석계(BigQuery/dbt/Iceberg) 친화성 상대적으로 낮음, 코드젠 부담 큼 | ❌ 기각 |
| JSON | 사람이 읽기 쉬움, 툴링 풍부 | 페이로드 비대(처리량·비용 불리), 스키마 강제가 별도 도구(JSON Schema) 의존 | ❌ 기각 |

상세: [ADR-008](#adr-008-직렬화-포맷--avro-vs-protobuf-json--kafka-스키마-운영).

### 6.2 Data Dictionary
| Entity | Field | Type | Constraint | Description |
|---|---|---|---|---|
| Telemetry | event_id | STRING(ULID) | PK, idempotency key | 이벤트 고유 id. **생성기가 이벤트 생성 시점에 1회 발급하며 publish 재시도에도 불변**(멱등키 계약 — doc_id·dedup의 성립 조건) |
| Telemetry | vehicle_id | STRING | NOT NULL, partition key | 차량 식별자(파티션/정렬 키) |
| Telemetry | event_time | TIMESTAMP | NOT NULL | 이벤트 발생 시각(이벤트타임) = **생성기가 publish하는 시점의 wall-clock UTC**. 시간가속 시뮬(§7.1)에서도 시뮬 내부 시계가 아니라 실제 발행 시각을 기록 — dedup TTL(30분)·late 임계(7일, §6.4.1)의 시간 기준을 wall-clock으로 명확히 고정 |
| Telemetry | lat / lon | FLOAT64 | Bronze 원본 | WGS84 좌표(SUMO 내부 xy(m)→WGS84 변환 후, §6.6) |
| Telemetry | location | GEOGRAPHY / geo_point | Silver+ 파생 | BigQuery `GEOGRAPHY`=`ST_GEOGPOINT(lon,lat)`, ES `geo_point`(Kibana Maps 필수). lat/lon 순서 주의(§6.6) |
| Telemetry | speed_kph | FLOAT64 | >= 0 | 속도 |
| Telemetry | accel_mps2 | FLOAT64 | | 종방향 가속도(급가속·급브레이크 판정) |
| Telemetry | heading_deg | FLOAT64 | 0–360 | 진행 방위각 |
| Telemetry | rpm | INT64 | >= 0 | 엔진 RPM |
| Telemetry | fuel_pct | FLOAT64 | 0–100 | 연료 잔량(%) |
| Telemetry | coolant_temp | FLOAT64 | | 냉각수 온도(과열 이상탐지) |
| Telemetry | ingest_time | TIMESTAMP | Silver+ 파생, NOT NULL | 수신 처리 시각(파이프라인 부여) — 지연 관측 `lag = ingest_time - event_time`(§6.4.1) |

### 6.3 Data Lifecycle
- **Creation**: 생성기/리플레이 → Kafka `telemetry.raw` publish.
- **Retention**: Bronze는 GCS lifecycle로 **90일 Standard 보관 후 Coldline 이관, 데이터 삭제 없음**(포트폴리오 총량 수십 GB — Coldline $0.004/GiB·월 수준으로 무시 가능, [Cloud Storage pricing](https://cloud.google.com/storage/pricing)). **Silver(Iceberg)는 GCS lifecycle 90일→Coldline**(Bronze와 동일 정책 — Iceberg 메타데이터 스냅샷 보존을 위해 데이터 자체는 삭제하지 않음, v1.0의 "BigQuery 180일 파티션 만료"에서 변경). Gold(BigQuery)는 **파티션 만료 180일**(분석 소용량, 데모·회고 기간 커버, [Managing partitioned tables](https://cloud.google.com/bigquery/docs/managing-partitioned-tables)).
- **Archival**: Bronze/Silver Iceberg 스냅샷 → GCS Coldline(90일 경과분).
- **Iceberg 테이블 유지보수(데이터 삭제와는 별개)**: Bronze·Silver는 행 데이터를 보존하지만, **오래된 스냅샷·고아(orphan) 데이터 파일**은 `iceberg_maintenance` DAG(일 1회, §7.4)가 정리한다 — `rewrite_data_files`(compaction) + `expire_snapshots`(7~30일 보존) + `remove_orphan_files`([Maintenance — Apache Iceberg](https://iceberg.apache.org/docs/latest/maintenance/), [Flink TableMaintenance](https://iceberg.apache.org/docs/latest/flink-maintenance/)). 이는 스토리지 비용·메타데이터 크기 관리를 위한 테이블 유지보수이며, **Retention 정책상 데이터 삭제와는 별개**(만료된 스냅샷이 가리키던 옛 파일만 정리, 현재 스냅샷의 데이터는 보존).
- **Deletion**: Gold는 파티션 만료(`partition_expiration_days=180`), Bronze·Silver(Iceberg)는 행 데이터 삭제 없음(Coldline 보관 + `iceberg_maintenance`의 스냅샷/고아 파일 정리만).

### 6.4 Data Flow (Medallion)
| 계층 | 처리 | 저장 |
|---|---|---|
| Bronze | Kafka 원본 append-only — dedup TTL 밖 중복 포함 가능(§6.4.1). 스키마 불량은 Bronze가 아니라 DLQ(GCS)에 별도 무손실 보존(§6.7) | **GCS+Iceberg**(Flink 싱크) |
| Silver | 중복제거·스키마검증·타입정리·이상치제거·차량메타 조인 | **GCS+Iceberg**(Flink 싱크) — v1.0의 BigQuery에서 변경 |
| Gold | 목적별 집계(분당 평균속도·급브레이크·연비·이상 플래그) — dbt가 BigLake로 Silver Iceberg를 읽어 생성 | BigQuery |

### 6.4.1 처리 의미론 (exactly-once 경로 · dedup · late data)

**exactly-once 경로 — Flink 체크포인트 + Kafka 오프셋 + Iceberg 2PC:**

| 단계 | 메커니즘 | 근거 |
|---|---|---|
| 발급 | 생성기가 `event_id`(ULID) 1회 발급, publish 재시도에도 불변 | 멱등키 계약(§6.2, §7.1) |
| 수집 | Kafka at-least-once(producer `acks=all`) | 소비자 dedup 필요(ADR-002) |
| 소스 오프셋 | Flink Kafka 소스가 컨슈머 오프셋을 **체크포인트에 포함**해 스냅샷 — 장애 시 마지막 성공 체크포인트의 오프셋으로 재탐색(replay) | [Checkpointing — Apache Flink](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/checkpointing/) — "지속가능한 소스는 일정 기간 레코드를 재생할 수 있어야 한다"는 전제를 Kafka가 충족 |
| 체크포인트 정렬 | **Chandy-Lamport 변형(비동기 배리어 스냅샷)** — 배리어가 지나간 시점까지의 오퍼레이터 상태·소스 오프셋을 일관된 스냅샷으로 저장(체크포인트 모드 = `EXACTLY_ONCE`, 저장소 = GCS) | [Fault Tolerance — Apache Flink](https://nightlies.apache.org/flink/flink-docs-stable/docs/learn-flink/fault_tolerance/) |
| 스트림 dedup | Flink **`keyBy(event_id)` + 상태(ValueState) TTL 30분** — Beam Deduplicate와 동등한 역할을 네이티브 Flink 상태로 구현(v1.0의 Beam Deduplicate 대체) | 30분은 재전달·재처리 지연 흡수 마진(운영 값, §7.1 부하시험으로 보정) |
| 중복 판정 키 | `event_id` = **명시적 `keyBy` + `ValueState` TTL**(구현 코드, TTL 30분) | §6.5 |
| Iceberg 싱크 | **2PC(Two-Phase Commit) 원자 커밋**: 체크포인트 배리어 통과 시 각 writer가 데이터 파일을 "pre-commit" 상태로 flush하고, 체크포인트가 전역적으로 성공하면 JobManager의 커미터가 Iceberg 스냅샷을 원자적으로 append — 체크포인트 실패 시 미완료 파일은 커밋되지 않아 Silver/Bronze에 부분 쓰기가 남지 않는다 | [Flink Connector — Apache Iceberg](https://iceberg.apache.org/docs/latest/flink-connector/), [FlinkSink Javadoc](https://iceberg.apache.org/javadoc/1.3.0/org/apache/iceberg/flink/sink/FlinkSink.html) |
| ES 싱크 | `doc_id=event_id` 멱등 upsert(트랜잭션 싱크가 아니므로 2PC 대상 아님 — 재시도해도 안전) | ADR-006 |
| **정합성 요약** | 장애 발생 시 Flink는 **마지막 성공 체크포인트**로 롤백한다 → Kafka 오프셋 재탐색(재전달 발생) → `keyBy` dedup이 재전달 중복을 걸러냄 → Iceberg는 체크포인트 단위 원자 커밋이라 부분 스냅샷이 노출되지 않음 → ES는 멱등 upsert로 재전달을 흡수. 이 4단 조합이 "effectively exactly-once"(G-1)를 구성한다 | §6.4.1 전체 |

**late data:**
- 코어 잡에는 스트림 집계가 없다(정제·라우팅만, §6.4) — 윈도우 사용처는 **dedup 상태 TTL(30분)뿐**이며 집계용 이벤트타임 윈도우는 존재하지 않는다(v1.0과 동일 — Flink 코어에도 windowing 미사용).
- late(지연) 이벤트도 **event-time 그대로 무기한 수용**한다: Iceberg Silver는 `event_time` 파티션(hidden partitioning, §6.8)에 배치되므로 늦게 도착해도 올바른 파티션에 적재된다. **watermark 초과를 이유로 이벤트를 폐기(discard)하지 않는 것이 무손실 원칙(G-1)과 정합** — allowed lateness로 데이터를 버리는 설계는 채택하지 않는다.
- `ingest_time`(수신 처리 시각) 컬럼으로 지연을 관측한다: `lag = ingest_time - event_time`.
- **7일 초과 지연 행**은 dbt 커스텀 테스트(`lag > 7d` 행 플래그, §7.3)로 잡고, 소스 적재 신선도는 source freshness로 감시해 운영 가시성을 확보한다.
- **잔존 중복 리스크(정직한 한계)**: Flink `keyBy` dedup은 상태 TTL 기반이며, TTL(30분) 밖 재전달은 Iceberg 커밋 단계에서도 별도 dedup을 하지 않는다(2PC는 "부분 쓰기 방지"이지 "값 중복 방지"가 아님) → **Silver에 드물게 중복 잔존 가능**. 방어선은 **차단(block)과 탐지(tripwire)로 분리**된다: ① **차단** — `stg_telemetry`의 `ROW_NUMBER() OVER (PARTITION BY event_id)` dedup(§7.3, BigLake 경유 조회 시점)이 Gold 유입을 차단. ② **탐지** — dbt **source-level** `unique(event_id)` 테스트(**silver 원본 대상** — stg dedup 이후에 걸면 항상 통과라 무의미, §7.3)가 **`severity: warn`로 고정된 tripwire**로 잔존 중복을 경고 기록한다(실패로 처리하지 않음 — G-4의 "dbt test 전체 통과" 목표와 설계상 상충하지 않도록 의도적으로 warn, §7.3·§9). ES는 doc_id 멱등이라 안전, Bronze는 중복 허용이 설계 의도(§6.4).

### 6.5 Storage Strategy (Polyglot Persistence)

저장소는 **역할별 polyglot**으로 나누고, "정본(source of truth) vs 서빙(사본)"을 명시적으로 구분한다. **v2.0은 Iceberg가 오픈포맷 backbone(Bronze+Silver)이고, BigQuery는 최종 분석/ML 층(Gold)으로 축소된다.**

| 저장소 | 역할 | 정본 여부 | 근거 |
|---|---|---|---|
| **GCS + Iceberg** (Bronze) | 수집 원본 무손실 보관(append-only) | **원본 정본** | 오픈포맷·time travel·스키마 진화. 손실 시 복구 불가 → 불변 유지 |
| **GCS + Iceberg** (Silver) | 정제 데이터 — 오픈포맷 backbone | **정제 정본** | v1.0의 "Silver=BigQuery"에서 변경. 엔진 비종속(Flink/dbt/DuckDB 모두 직접 조회 가능, §15) |
| **BigQuery** (Gold, BigLake 경유) | 집계·이상탐지(BQ ML) 최종 분석 층 | **분석 정본** | OLAP 웨어하우스. 대량 스캔·집계·조인·시계열·ML에 최적. **BigLake 외부테이블(read-only)로 Silver Iceberg를 직접 조회**해 이동 없이 생성([Create Apache Iceberg external tables](https://docs.cloud.google.com/bigquery/docs/iceberg-external-tables)) |
| **Elasticsearch** | 실시간 검색·지도·알림 서빙 | **아님(재구성 가능 사본)** | 유실/재색인 시 Bronze/Silver Iceberg에서 **재구성**. 저지연 단건·지리 조회 담당 |
| **(Phase 3 확장) Cloud SQL** | 차량 레지스트리/메타 dim, 멱등성 inbox | 참조 정본(소규모, Phase 3) | 코어(Phase 1-2)는 `dim_vehicle`·`dim_geofence`를 dbt seed로 시작(§7.3) — 변경 잦은 관계형 메타·CDC(Debezium/아웃박스) 데모·`processed-events` 멱등 테이블은 Phase 3 확장 트랙(§16) |

**설계 원칙 (왜 이렇게):**
- **ES는 정본이 아니다.** 실시간 서빙 속도를 위한 파생 사본이며, 언제든 정본(Bronze/Silver Iceberg)에서 다시 만들 수 있어야 한다 → **ES 단독 저장 금지.**
- **BigQuery ≠ RDB.** OLAP 컬럼형이라 PK/FK를 강제하지 않고(단건 UPDATE/조회에 부적합), 인덱스 대신 **파티션(`event_time`)+클러스터(`vehicle_id`)** 로 성능·비용을 제어한다. v2.0에서는 Gold 전용이라 규모가 v1.0(Silver+Gold)보다 작다.
- **텔레메트리는 append-only 이벤트**라 트랜잭션 RDB가 불필요하다. 변경형 관계 데이터(차량 등록/변경)만 선택적으로 Cloud SQL에 둔다.
- **유실·정합성은 저장소 종류가 아니라 파이프라인이 보장한다**: Bronze 불변 원본 + Flink 체크포인트 exactly-once(`keyBy(event_id)` dedup) + DLQ(무손실 격리) + Iceberg 재처리(batch 모드). (참조: [ADR-004](#adr-004-polyglot-저장소-역할-분리-정본-vs-서빙))
- **Iceberg 중심 전환의 이점**: BigQuery 의존이 Gold 층으로 축소되어(§15, ADR-011) 로컬 테스트 커버리지가 v1.0보다 넓어진다 — Kafka→Flink→Iceberg→ES 전 구간을 컨테이너로 로컬 재현 가능.

### 6.6 Geospatial Handling

좌표는 계층마다 **다른 타입**으로 표현한다.

| 계층 | 필드 / 타입 | 비고 |
|---|---|---|
| Bronze(Iceberg) | `lat`, `lon` : FLOAT64 | WGS84 원본 그대로 보관 |
| Silver(Iceberg)/Gold(BigQuery) | `location` : **GEOGRAPHY**(Gold) / FLOAT64 쌍(Silver Iceberg 원시 저장, BigLake 조회 시 dbt가 `ST_GEOGPOINT`로 변환) | Gold의 `ST_DWITHIN`(지오펜싱)·`ST_DISTANCE`(주행거리) 활용 |
| Elasticsearch | `location` : **geo_point** | Kibana **Maps·히트맵의 필수 타입**. 미지정 시 지도 시각화 불가 |

**설계 함정:**
- **좌표계 변환**: SUMO 내부 좌표는 미터 단위 xy다. WGS84 위경도로 변환해야 함 — `traci.simulation.convertGeo(x, y)`(LuST 시나리오는 geo-referenced). 생성기(§7.1)에서 변환 후 publish.
- **lat/lon 순서 함정**: BigQuery/GeoJSON은 **`(lon, lat)`**, Elasticsearch 문자열은 **`"lat,lon"`**. 순서를 뒤집으면 좌표가 엉뚱한 곳(예: 바다)에 찍힌다. 파이프라인 전 구간에서 순서 규약을 고정한다.

### 6.7 DLQ 설계

**분류 4종:**

| 분류 | 원인 | 예시 |
|---|---|---|
| `PARSE_FAILURE` | Avro 디코드 실패 | 손상된 바이트열, 스키마 불일치 |
| `SCHEMA_VALIDATION_FAILURE` | 필드 범위·필수값 위반 | `speed_kph < 0`, `event_id` 누락 |
| `BUSINESS_RULE_FAILURE` | 업무 규칙 위반 | 미등록 `vehicle_id`(`dim_vehicle` 미존재) 등 |
| `SINK_WRITE_FAILURE` | 싱크 write 재시도 상한 초과 | ES bulk reject/매핑 충돌(→GCS `dlq/es/`) — 동일 envelope 사용, `pipeline_step`으로 싱크 식별. **Iceberg 싱크는 체크포인트 2PC로 부분 쓰기가 없어 개별 레코드 단위 격리 대상이 아니며, 지속 실패 시 잡 레벨 재시도로 처리한다(§5.2)** — v1.0의 `dlq/bq/`(BQ Storage Write 실패)는 Silver가 BigQuery에서 Iceberg로 이전되며 소멸 |

Envelope 스키마: [`schemas/dlq-envelope.avsc`](../schemas/dlq-envelope.avsc)(`DlqEnvelope`) — `original_payload`, `error_class`, `error_detail`, `source_subscription`, `pipeline_step`, `processing_time`, `attempt`. **스키마 자체는 v1.0과 동일(변경 없음)**.

**재처리 절차 — `error_class`별 분기:**

*검증 실패 3종(`PARSE_FAILURE`/`SCHEMA_VALIDATION_FAILURE`/`BUSINESS_RULE_FAILURE`, `telemetry.dlq` 경유) 전용:*
1. DLQ topic(`telemetry.dlq`) → **GCS 싱크 컨슈머**(Flink 잡 또는 Kafka Connect)로 원본을 무손실 보존(append-only).
2. 운영자가 GCS의 `DlqEnvelope` 레코드를 `error_class`/`error_detail` 기준으로 조회·분석.
3. 원인 수정(스키마 패치, `vehicle_id` 레지스트리 등록 등) 후 **재발행 CLI**로 `telemetry.raw`에 재publish.
4. 재발행 안전성의 실제 근거: **검증 실패 3종에 한해, DLQ로 격리된 메시지는 어떤 싱크에도 도달한 적이 없다**(검증 시점에 분기 — 다중 싱크 fork 이전) — 재발행은 신규 적재와 동일하다. 운영자 재처리는 통상 dedup TTL(30분)을 지나 일어나므로 dedup에 기대지 않는다. 이미 처리된 이벤트의 실수 재발행 방지를 위해 재발행 CLI에 **Iceberg Silver `event_id` 존재 사전 조회 가드**를 둔다.

*`SINK_WRITE_FAILURE`(GCS `dlq/es/` 직행) 전용 — 위 절차 미적용:* 이 클래스는 검증 통과 후 ES 싱크 write만 실패한 이벤트라 **Iceberg(Bronze/Silver)에는 이미 도달**했다. 재발행이 아니라 §5.2의 ES 복구 경로(재색인)를 따른다.

### 6.8 계층별 저장 설계

**Bronze (Iceberg) — 파티션 스펙:**
`days(event_time)` — Iceberg **hidden partitioning**(파티션 컬럼을 물리적으로 노출하지 않고 쿼리 시 자동 프루닝, [Partitioning](https://iceberg.apache.org/docs/latest/partitioning/)). `vehicle_id` 버킷 파티션은 기각 — 수백 대 규모 fleet에서 차량당 파일이 과도하게 쪼개져 small-file 폭증을 유발한다.

**Silver (Iceberg) — Flink DDL(Iceberg 테이블):**

```sql
-- Flink SQL (Iceberg 카탈로그) — Silver 정제 테이블
CREATE TABLE iceberg_catalog.silver.telemetry_events (
  event_id      STRING    NOT NULL,   -- ULID, 멱등키(§6.2)
  vehicle_id    STRING    NOT NULL,
  event_time    TIMESTAMP(3) NOT NULL,-- 이벤트타임, 파티션 컬럼
  ingest_time   TIMESTAMP(3) NOT NULL,-- 처리 시각, 지연 관측(§6.4.1)
  lat           DOUBLE,
  lon           DOUBLE,
  speed_kph     DOUBLE,
  accel_mps2    DOUBLE,
  heading_deg   DOUBLE,
  rpm           BIGINT,
  fuel_pct      DOUBLE,
  coolant_temp  DOUBLE,
  PRIMARY KEY (event_id) NOT ENFORCED
) PARTITIONED BY (days(event_time))
WITH (
  'format-version' = '2',
  'write.upsert.enabled' = 'true'   -- keyBy dedup 통과분 upsert, §6.4.1
);
```

- 파티션은 Bronze와 동일하게 `days(event_time)` hidden partitioning.
- `format-version=2`(Iceberg v2, row-level delete 지원)로 upsert를 허용해 재처리 시 동일 `event_id` 레코드를 덮어쓸 수 있게 한다.
- **`write.upsert.enabled`는 파티션 스코프 equality delete**라 같은 `event_time` 파티션 내 재기록만 안전하게 덮어쓴다 — late 재전달로 event_time이 달라져 다른 파티션에 적재되면 이전 파티션의 중복은 upsert가 제거하지 못한다 → stg `ROW_NUMBER` dedup(§7.3)이 여전히 필요한 belt-and-suspenders 방어선인 이유(잔존 중복 리스크, §6.4.1).

**Gold (BigQuery, dbt via BigLake) — 5개 집계 테이블 + `dim_vehicle`:**

BigLake 외부테이블 정의(Silver Iceberg를 BigQuery에서 조회하기 위한 진입점, dbt source):

```sql
-- BigLake 외부테이블 — Silver Iceberg를 BigQuery에서 조회
-- 아래는 JSON 메타데이터 파일 방식(수동 refresh 필요, GCP는 Azure 대상에만 권장)의 예시다.
-- prod는 **BigLake metastore(Lakehouse runtime catalog) 경유** — Iceberg REST catalog 엔드포인트를
-- BigLake 연결에 등록해 Flink 커밋(60초 주기, §7.2)마다 BigQuery가 최신 스냅샷을 자동 조회한다
-- (수동 metadata refresh 불필요, 카탈로그 전환 상세는 §16.1).
CREATE EXTERNAL TABLE `silver.telemetry_events_biglake`
WITH CONNECTION `us.biglake-connection`
OPTIONS (
  format = 'ICEBERG',
  uris = ['gs://fleetsentinel-silver/telemetry_events/metadata/*']  -- 수동 방식 예시. prod는 metastore 카탈로그 참조로 대체
);
-- 참고: BigLake Iceberg 외부테이블은 read-only(Flink write, BQ read) —
-- BigQuery 관리형 Iceberg 테이블(DML 가능)과는 다른 구성. §12.4 근거.
-- ([Create Apache Iceberg external tables](https://docs.cloud.google.com/bigquery/docs/iceberg-external-tables),
--  [Query Apache Iceberg external tables](https://docs.cloud.google.com/bigquery/docs/query-iceberg-data),
--  [About the Lakehouse runtime catalog](https://docs.cloud.google.com/lakehouse/docs/about-lakehouse-catalogs))
```

```sql
-- 차량·분당 평균/최대 속도
CREATE TABLE `gold.agg_speed_minute` (
  vehicle_id     STRING    NOT NULL,
  minute_ts      TIMESTAMP NOT NULL,
  avg_speed_kph  FLOAT64,
  max_speed_kph  FLOAT64
)
PARTITION BY DATE(minute_ts)
CLUSTER BY vehicle_id;

-- 급가속·급브레이크: |accel_mps2| > 3.0
-- 근거: harsh braking 0.3g(≈2.94 m/s²) 관례를 보수적으로 3.0 m/s²로 반올림하고, 제동 임계를 급가속에도 대칭 적용(설계 선택·단순화).
-- 출처: Meuleners et al. 2023 — Boylan, Meyer & Chen 2025(J. Road Safety)에서 재인용된 관례 임계(해당 2025 연구 자체는 민감도 목적으로 0.2g 사용).
-- https://journalofroadsafety.org/article/128557-the-influence-of-vehicle-characteristics-on-the-braking-behaviour-of-young-people-as-measured-using-telematics
CREATE TABLE `gold.agg_harsh_events` (
  vehicle_id  STRING    NOT NULL,
  event_time  TIMESTAMP NOT NULL,
  event_type  STRING    NOT NULL,  -- HARSH_ACCEL | HARSH_BRAKE
  accel_mps2  FLOAT64   NOT NULL
)
PARTITION BY DATE(event_time)
CLUSTER BY vehicle_id;

-- 차량·시간당 연료소모 vs 주행거리(ST_DISTANCE 기반)
CREATE TABLE `gold.agg_fuel_efficiency` (
  vehicle_id         STRING    NOT NULL,
  hour_ts            TIMESTAMP NOT NULL,
  fuel_consumed_pct  FLOAT64,
  distance_km        FLOAT64
)
PARTITION BY DATE(hour_ts)
CLUSTER BY vehicle_id;

-- 과열: coolant_temp > 105°C 지속
-- 근거: 엔진 정상 운전 범위 상한 90–105°C, 105°C 초과 시 과열로 간주 — 데모용 휴리스틱 임계(출처: 튜닝 기술교육 블로그, OEM/SAE 정식 기준 아님)
-- https://www.hpacademy.com/technical-articles/coolant-temperatures-what-is-safe-quick-tech/
CREATE TABLE `gold.agg_overheat` (
  vehicle_id    STRING    NOT NULL,
  event_time    TIMESTAMP NOT NULL,
  coolant_temp  FLOAT64   NOT NULL,
  duration_sec  INT64
)
PARTITION BY DATE(event_time)
CLUSTER BY vehicle_id;

-- 지오펜스 진입/체류: ST_DWITHIN 기반
CREATE TABLE `gold.agg_geofence_dwell` (
  vehicle_id     STRING    NOT NULL,
  geofence_id    STRING    NOT NULL,
  enter_time     TIMESTAMP NOT NULL,
  dwell_seconds  INT64
)
PARTITION BY DATE(enter_time)
CLUSTER BY vehicle_id;

-- 지오펜스 정의 dim — 지오펜스 집계의 참조 정본. 판정: ST_DWITHIN(location, center, radius_m)
CREATE TABLE `gold.dim_geofence` (
  geofence_id  STRING NOT NULL,
  name         STRING,
  center       GEOGRAPHY,   -- ST_GEOGPOINT(lon, lat), §6.6
  radius_m     FLOAT64
);

-- 차량 메타 dim, 조인 키 = vehicle_id
CREATE TABLE `gold.dim_vehicle` (
  vehicle_id     STRING NOT NULL,
  vehicle_type   STRING,
  registered_at  TIMESTAMP,
  fleet_group    STRING
);

-- 이상탐지 뷰(ADR-010) — BQ ML 시계열 이상 탐지 대상(Gold 위)
CREATE MODEL `gold.model_speed_anomaly`
OPTIONS(model_type='ARIMA_PLUS', time_series_timestamp_col='minute_ts',
        time_series_data_col='avg_speed_kph', time_series_id_col='vehicle_id') AS
SELECT vehicle_id, minute_ts, avg_speed_kph FROM `gold.agg_speed_minute`;
```

**Elasticsearch — 단일 인덱스 + index template (data stream 미사용):**

```json
{
  "index_patterns": ["telemetry-fleet"],
  "template": {
    "mappings": {
      "properties": {
        "event_id":     { "type": "keyword" },
        "vehicle_id":   { "type": "keyword" },
        "event_time":   { "type": "date" },
        "location":     { "type": "geo_point" },
        "speed_kph":    { "type": "float" },
        "accel_mps2":   { "type": "float" },
        "heading_deg":  { "type": "float" },
        "rpm":          { "type": "long" },
        "fuel_pct":     { "type": "float" },
        "coolant_temp": { "type": "float" }
      }
    }
  }
}
```

- **data stream을 쓰지 않는 이유**: data stream은 append-only(`op_type=create`만 허용)라 `_id` 기반 **upsert가 불가**하고, `_id` 유일성도 backing index 단위라 ILM rollover 이후의 재전달 중복을 막지 못한다([Use a data stream](https://www.elastic.co/docs/manage-data/data-store/data-streams/use-data-stream)). 멱등 upsert(ADR-006)가 exactly-once 서사의 핵심이므로 **단일 일반 인덱스**를 채택한다.
- `_id = event_id`(keyword) — 멱등 upsert 근거(§5.2, ADR-006).
- **보존 정책**: ILM rollover 대신 **일 1회 delete-by-query**(`event_time < now-30d`, Airflow `es_retention_daily`, §7.4) — 서빙 사본 원칙(정본은 Bronze/Silver Iceberg, ADR-004)에 따라 ES는 30일 단기 보관. 데모 규모(수백만 문서)에서 delete-by-query 비용은 무시 가능.
- **Gold→ES 타깃**: 집계 결과는 별도 인덱스 `telemetry-gold-daily`(문서 수 적음, 보존 365일)로 적재해 Kibana 장기 트렌드 대시보드가 사용. Gold 테이블들의 시간 컬럼이 제각각(minute_ts/hour_ts/enter_time/event_time)이므로 **export 시 공통 `@timestamp` 필드로 정규화**해 적재하고, 보존 delete-by-query도 `@timestamp < now-365d` 기준으로 실행. 장기 이력의 정본은 BigQuery Gold(§6.5) — ES 단기 보존과 장기 트렌드 요구의 충돌은 이 이원화로 해소.
- 수치 필드는 avsc `double` → ES `float`(32-bit) 다운캐스트 — 서빙 사본이라 수용(미세 정밀도 손실), 분석 정본(Iceberg/BQ)은 FLOAT64/DOUBLE 유지.

---

## 7. Component Design

### 7.1 Telemetry Generator (Python)
- **Responsibility**: SUMO/리플레이로 fleet 텔레메트리 생성 → **Kafka publish**(시간가속 지원).
- **Inputs**: SUMO 시나리오(LuST 맵, fleet **500대**, `--step-length` 1s → 차량당 1Hz 샘플 = 500 eps 기본, [SUMO 시간 스텝 정의](https://sumo.dlr.de/docs/Simulation/Basic_Definition.html)) / Kaggle Levin OBD-II 로그(실측 분포 보정 — comma2k19는 §13 R-2 근거로 기각). **Outputs**: Kafka `telemetry.raw` 메시지(key=vehicle_id, Avro binary).
- **런타임**: 개발·데모=로컬 실행(sumo-gui), 부하시험·장기 실행은 **Cloud Run Jobs**(컨테이너, 최대 24h, 서버리스 과금) — Kafka/Flink/ES 클러스터(self-host)와 별개로 생성기만 서버리스 유지. GKE/GCE 상시 노드에 생성기를 얹으면 데모용 저지속 워크로드가 상시 노드 비용에 얹혀 비효율적이라 기각. 24h 초과 시나리오는 **시간 구간+고정 시드로 분할**해 각 잡이 독립 구간을 실행(구간 경계 cold-start 불연속은 부하시험 한정 용도로 수용; 차량 단위 연속 궤적 분석에는 미사용).
- **시간가속(부하시험)**: SUMO 시뮬레이션은 headless에서 wall-clock에 페이싱되지 않고 **연산 속도만큼 빠르게(as-fast-as-possible) 스텝을 진행**한다 — 가속의 메커니즘은 `--step-length`(스텝당 시뮬 시간 해상도, 1Hz 샘플의 근거)가 아니라 **생성기가 TraCI 스텝 루프의 소비 속도를 목표 배율(10x)로 제어**하는 것이다(sumo-gui의 delay가 실시간 페이싱용인 것과 대비, [sumo-gui delay](https://sumo.dlr.de/docs/sumo-gui.html)). 10x 가속 시 wall-clock 초당 5,000 이벤트가 발행되어 **피크 5,000 eps** 부하가 재현된다. `event_time`은 시뮬 시계가 아닌 **발행 시점 wall-clock UTC**(§6.2) — 가속해도 파이프라인이 겪는 이벤트타임 분포는 실제 스트리밍 상황과 동일. 단, **가속 세션 데이터는 파이프라인 검증(처리량·지연·정합) 전용**이며 Gold 물리 지표(연비·주행거리 등) 해석에는 사용하지 않는다(10x 시 시간당 이동거리 등이 물리적으로 왜곡). **10x 배율 자체는 시뮬 연산 성능(CPU) 의존의 목표치**다 — LT-LOAD-01 사전 캘리브레이션(vCPU당 달성 eps 실측, §15)으로 확정하고, 미달 시 차량 수 상향 또는 합성 생성기 병행으로 목표 eps를 보정한다.
- **Core Logic**: TraCI 폴링 or 로그 리플레이 → **`event_id`(ULID) 1회 발급(publish 재시도에도 재사용·불변)** → Avro 직렬화 → Kafka publish.

### 7.2 Flink Stream Processor (Java + Apache Flink, self-host)
- **Responsibility**: 단일 잡 **다중 싱크** — Bronze Iceberg 적재 + Silver Iceberg 정제 + ES 실시간 색인(ADR-006).
- **Inputs**: Kafka `telemetry.raw` consumer group. **Outputs**: ①Iceberg Bronze(raw) ②Iceberg Silver(정제) ③ES(`doc_id=event_id` 멱등 upsert), 불량→DLQ(스키마 실패=`telemetry.dlq`, ES write 실패=GCS `dlq/es/`).
- **Core Logic**: `keyBy(event_id)` dedup(상태 TTL 30분, §6.4.1) → 스키마 검증 → 차량 메타 enrich → 다중 싱크(체크포인트 기반 exactly-once, 집계용 이벤트타임 윈도우 없음).
- **런타임 구성**: JobManager 1 + TaskManager N(RocksDB state backend), 체크포인트 간격 **60초**, 저장소 = GCS(`execution.checkpointing.storage=filesystem`, [Checkpointing — Apache Flink](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/checkpointing/)), 체크포인트 모드 = `EXACTLY_ONCE`.
- **enrich side-input 계약**: 차량 메타는 **로컬/prod 동일하게 GCS의 fleet 정의 CSV(생성기와 동일 소스, §7.1)를 잡 기동 시 브로드캐스트 상태(Broadcast State)로 1회 로드**해 enrich에 사용한다 — **BigQuery READ 없음**(sa-flink에 BQ 권한이 불필요하다는 §5.3 결정과 정합). `gold.dim_vehicle`(dbt seed, §7.3)은 **Gold 조인 검증 전용**(dbt `relationships` 테스트)으로만 쓰이며 enrich 경로와는 분리된다. fleet 정의는 정적(생성기와 동일 CSV 소스)이므로 갱신은 잡 업데이트 시에만 발생 — Phase 3 CDC 확장 전까지 refresh 메커니즘 불필요. `BUSINESS_RULE_FAILURE`(미등록 vehicle_id, §6.7) 판정도 동일 broadcast state 기준이라 **순환 의존 없음**(dim이 텔레메트리에서 파생되지 않음, dim_vehicle CSV는 Gold 검증용과 별도 소스 계보).

### 7.3 Transform (dbt / SQL, BigLake 경유)
- **Responsibility**: Silver(Iceberg, BigLake 외부테이블)→Gold(BigQuery) 집계 + 데이터 품질 테스트(`unique`/`not_null`/`accepted_range`/`relationships`, store_failures).
- **모델 트리**:
  ```
  models/
    staging/
      stg_telemetry.sql        -- view, BigLake 외부테이블(silver.telemetry_events_biglake) 1:1 정제 + ROW_NUMBER() OVER (PARTITION BY event_id) dedup(§6.4.1 잔존 중복 차단)
    marts/
      dim_geofence.csv (seed)  -- 정적 데모 지오펜스 → gold.dim_geofence 적재(dbt seed)
      dim_vehicle.csv (seed)   -- 생성기 fleet 500대 정의와 동일 소스 CSV → gold.dim_vehicle (dbt seed)
      agg_speed_minute.sql     -- incremental, insert_overwrite(파티션: minute_ts)
      agg_harsh_events.sql     -- incremental, insert_overwrite(파티션: event_time)
      agg_fuel_efficiency.sql  -- incremental, insert_overwrite(파티션: hour_ts)
      agg_overheat.sql         -- incremental, insert_overwrite(파티션: event_time)
      agg_geofence_dwell.sql   -- incremental, insert_overwrite(파티션: enter_time)
    ml/
      model_speed_anomaly.sql  -- BQ ML CREATE MODEL(ARIMA_PLUS), ADR-010
  ```
- **BigLake 소스 선언**(`sources.yml`): `stg_telemetry`가 참조하는 `silver.telemetry_events_biglake`는 dbt source로 등록 — dbt 자체는 Iceberg를 직접 읽지 않고 **BigQuery가 BigLake 커넥션으로 Silver Iceberg 메타데이터를 조회**하는 구조([Query Apache Iceberg external tables](https://docs.cloud.google.com/bigquery/docs/query-iceberg-data)).
- **품질 테스트**(`store_failures` 전역 활성, [Data tests](https://docs.getdbt.com/docs/build/data-tests)):

  | 테스트 | 대상 |
  |---|---|
  | `unique`(**source test**, `severity: warn` 고정) | silver `telemetry_events_biglake.event_id` — stg dedup **이전** 원본 대상(§6.4.1 tripwire — 차단이 아니라 경고, G-4와 비상충) |
  | `not_null` | `event_id`, `vehicle_id`, `event_time`, `lat`, `lon` |
  | `dbt_utils.accepted_range` | `speed_kph`(0~300), `fuel_pct`(0~100), `heading_deg`(0~360) |
  | `relationships` | `vehicle_id` → `dim_vehicle.vehicle_id` |
  | custom test + source freshness | `lag = ingest_time - event_time` > 7d 행 플래그(§6.4.1) + 소스 적재 신선도 감시 |

### 7.4 Orchestration (Airflow / Python, 로컬(개발) / 클라우드 세션 시 GKE in-cluster, §5.3)
- **Responsibility**: dbt 실행·의존성·백필 스케줄, Flink 잡 제출/모니터링, 파이프라인 헬스.
- **DAG 5개**:

  | DAG | 스케줄 | 의존성 | 책임 | 구분 |
  |---|---|---|---|---|
  | `dbt_hourly` | 매시 정각(단순 스케줄 — 별도 센서 없음) | dbt source freshness 검사가 Silver 적재 지연을 게이트 | `dbt run` → `dbt test`, 실패 시 알림(§10.2) | 스트레치(Gold 의존, §16.1) |
  | `bq_to_es_daily` | 매일 1회 | `dbt_hourly` 최신 성공 | Gold→ES 배치 export 기동(§5.2) | 스트레치(Gold 의존) |
  | `backfill_manual` | 수동 트리거(date-range 파라미터) | 없음(운영자 개시) | 지정 구간 **Bronze Iceberg 리플레이**(정본 소스) — Flink batch 모드 잡 기동 → 완료 후 dbt 재실행 | **MVP**(리플레이는 Bronze/Silver 코어 검증에 필요) |
  | `es_retention_daily` | 매일 1회 | 없음 | ES delete-by-query(`telemetry-fleet`: `event_time < now-30d` / `telemetry-gold-daily`: `@timestamp < now-365d`) — §6.8 보존 정책 집행 | 스트레치(서빙 의존) |
  | `iceberg_maintenance` | 매일 1회 | 없음 | `rewrite_data_files`(compaction) + `expire_snapshots`(7~30일 보존) + `remove_orphan_files` — Bronze/Silver Iceberg 유지보수(§6.3, [Maintenance — Apache Iceberg](https://iceberg.apache.org/docs/latest/maintenance/), [Flink TableMaintenance](https://iceberg.apache.org/docs/latest/flink-maintenance/)) | 스트레치(**MVP 후반** — Silver 의존이라 Gold/서빙보다 이르게 필요) |

### 7.5 Serving (Elasticsearch / Kibana, self-host)
- **Responsibility**: 실시간 위치·속도 히트맵(Maps), Kibana 규칙 기반 임계 알림(Basic tier). 학습 기반 이상탐지는 BigQuery ML이 담당(§4.1, ADR-010) — Elastic ML은 self-host Basic tier 미포함이라 사용하지 않는다.

---

## 8. Interface Design

### 8.1 Messaging Topics
| Topic | Producer | Consumer | Payload |
|---|---|---|---|
| `telemetry.raw` | 생성기 | Flink | Avro binary([`schemas/telemetry-event.avsc`](../schemas/telemetry-event.avsc)) |
| `telemetry.dlq` | Flink | 운영(GCS 싱크 컨슈머) | Avro binary(DLQ envelope, [`schemas/dlq-envelope.avsc`](../schemas/dlq-envelope.avsc)) |

**Kafka 클러스터·토픽 운영 계약(ADR-002/ADR-008/ADR-009 실행 조건):**
- 클러스터: **self-host KRaft**, 공식 `apache/kafka` 이미지, 단일 호스트 3-broker([Upgrading — Apache Kafka](https://kafka.apache.org/40/getting-started/upgrade/), [KRaft — Confluent](https://developer.confluent.io/learn/kraft/)). ZooKeeper 미사용, Strimzi 미사용.
- 복제: `replication.factor=3`, `min.insync.replicas=2`, `acks=all`, `unclean.leader.election.enable=false`, `offsets.topic.replication.factor=3`, `transaction.state.log.replication.factor=3`.
- 스키마: Avro는 **스키마 파일(`schemas/*.avsc`) + 클라이언트측 검증**으로 관리(별도 Schema Registry self-host는 옵션, ADR-008) — Terraform으로 토픽·ACL 관리(수동 콘솔/CLI 변경 금지).
- **스키마 핀 고정**: Schema Registry 미사용 → producer/consumer가 **동일 `.avsc` 파일을 핀 고정**(리더가 버전 관리, git 커밋으로 고정). 온-와이어 스키마 진화(리비전 자동 협상)는 지원하지 않고 **수동**(스키마 변경 시 재배포) — 동결 스키마(§6.1)라 MVP에는 영향 없음.
- **로컬 한계**: docker-compose Kafka는 실제 서버와 동일 이미지·모드라 로컬-dev 간 경로 차이가 없다(v1.0 Pub/Sub emulator의 스키마 검증 미지원 한계가 v2.0에서는 소멸, §15).

### 8.2 Internal Interfaces
- Bronze/Silver Iceberg 테이블 스키마(§6.8 Flink DDL) / BigQuery Gold 테이블 계약(dbt model contracts, BigLake source) — DDL 정본은 §6.8.
- Elasticsearch index mapping 정의 — 정본은 §6.8(단일 인덱스·보존정책 포함).

### 8.3 UI Flow
- Kibana 대시보드: 실시간 지도 → 차량 드릴다운 → 이상 이벤트 타임라인.

---

## 9. Non-Functional Requirements

| Category | Requirement | Acceptance Criteria |
|---|---|---|
| Performance | 서빙 지연 | p99 < 300ms(Kibana/ES 검색 기준) — 목표치, 실측 검증 §15 |
| Scalability | 처리량 | 5,000 rps sustained, 누적 1억+ 건(6h 부하시험 기준) — 목표치, 실측 검증 §15 |
| Reliability | 데이터 정확성 | 유실 0 / 중복 0 — **차단(block)**: Flink `keyBy` dedup(TTL 30분 내) + stg `ROW_NUMBER` dedup(TTL 밖 잔존 중복까지 Gold 유입 차단). **탐지(tripwire)**: dbt source `unique(event_id)`(`severity: warn` 고정)가 잔존 중복을 경고로 검출 — warn은 실패가 아니므로 G-4 "dbt test 통과" 목표와 비상충(§6.4.1·§7.3) |
| Availability | 파이프라인 | Flink 잡 무중단(체크포인트 재시작), Kafka 브로커 1개 kill까지 무손실(ADR-009) |
| Observability | 추적성 | RED/USE + 골든시그널 대시보드, DLQ·체크포인트 모니터링 |
| Maintainability | 데이터 품질 | dbt 테스트(error severity) 통과율 100%, `unique` tripwire(warn) 발동행은 별도 관측 지표로 추적 — G-4는 **스트레치(P5) 게이트**(§16.1) |
| Cost | 비용 | 월 GKE/GCE node-hours 기준 크레딧 $300 이내, 캠페인 stop/start로 상시 가동 회피 — 상세 §9.1 |

### 9.1 GCP 비용 추정 (월, GKE/GCE node-hours 기준)

전략: **상시 가동 없음 — Terraform으로 세션/캠페인 단위 up/down**. Kafka·Flink·ES 클러스터(GKE/GCE)는 데모/부하시험 세션에만 기동하고, 상시 비용은 스토리지(GCS/BQ)만 남긴다. v1.0의 "관리형 서비스 세션비"(Dataflow 워커시간·Elastic Cloud 캠페인비)가 **자체호스팅 노드-시간**으로 대체된다.

| 항목 | 추정(월) | 근거 |
|---|---|---|
| GKE 클러스터 관리비 | ~$0(크레딧 상쇄) | $0.10/시간 플랫 수수료([GKE pricing](https://cloud.google.com/kubernetes-engine/pricing)) — 구글이 계정당 매월 $74.40 GKE 크레딧을 자동 제공해 클러스터 1개 상시분을 사실상 상쇄 |
| Kafka 노드(단일호스트 3-broker) | ~$3 | `e2-standard-4`(4 vCPU/16GB) 1대, 세션 ~20h/월 × 서울 리전 약 $0.15/h(us-central1 $0.134/h 기준 아시아 리전 상단 프리미엄 반영, [Compute Engine pricing](https://cloud.google.com/compute/vm-instance-pricing)) ≈ $3 |
| Flink 클러스터(JobManager+TaskManager) | ~$8 | JobManager `e2-standard-2` 1대 + TaskManager `e2-standard-4` 2대, 세션 ~20h/월 ≈ ($0.08+$0.15×2)×20h ≈ $8 |
| Elasticsearch 노드(self-host, Basic) | ~$3 | `e2-standard-4` 1대, 세션 ~20h/월 ≈ $3(라이선스 비용 0, Basic tier 무료) |
| GKE PVC(Kafka/ES 로컬 디스크) | ~$2 | 소용량 SSD PD, 상시 유지(세션 간 상태 보존용) |
| BigQuery(Gold, BigLake 경유) | ~$5–8 | 스토리지 ~수 GB(Gold만, v1.0 대비 축소) + 파티션 프루닝된 쿼리(§6.8 파티션·클러스터) + BQ ML 학습/추론 쿼리 |
| GCS(Bronze+Silver Iceberg+체크포인트) | ~$5 | 수십 GB, Bronze+Silver 모두 Iceberg라 v1.0(Bronze만)보다 소폭 증가, 90일 후 Coldline 이관(§6.3) |
| **합계(세션 기반, ~20h/월)** | **~$26–29/월** | **크레딧 $300 대비 여유** |

- **상시 가동 압박 시나리오**: 위 GKE/GCE 노드(Kafka+Flink+ES, 총 4~5대 `e2-standard-4` 상당)를 24시간×30일 상시 가동하면 노드 컴퓨트만 (약 $0.15×5)×720h ≈ **월 $540+**로 크레딧을 크게 초과한다 — **캠페인(주 단위) 기동/삭제 또는 세션(일 단위) up/down**이 필수(§16 MVP는 소형 GKE 노드 2~3개로 2주 내 여유롭게 커버).
- **비용 산정의 기초 가정**: 이벤트 ≈ **300B**(Avro binary, §6.2 11필드 기준) × 5,000 eps × 세션 20h/월 ≈ **약 110GB/월** — GCS·BigQuery 추정의 산출 근거(v1.0과 동일 가정 유지).
- **최대 부하시험 월(상한 시나리오)**: 노드(Kafka+Flink+ES) $20 + PVC $2 + BigQuery $10 + GCS $8 ≈ **$40 내외** — 관리형 대비 v1.0($170–200)보다 크게 낮아진 것은 Elastic Cloud 관리형비($99+)가 self-host(라이선스 $0)로 대체되고, Dataflow/Composer 워커시간 과금이 정액에 가까운 소형 GKE 노드로 대체됐기 때문. **여유 확보분은 3-클러스터 self-host 운영 복잡도(§13 R-6)에 대응하는 완충으로 소비**(예비 노드, 반복 재기동 테스트).

---

## 10. Cross-Cutting Concerns

### 10.1 Security
- GCP IAM 최소 권한 서비스 계정, 시크릿은 Secret Manager, 전송/저장 암호화(GCP 기본). Kafka/Flink/ES는 VPC 내부 통신만 허용(§5.3).

### 10.2 Observability

- **기본 = Cloud Monitoring/Logging**(관리형 — GKE/GCE·BigQuery 지표 기본 제공). Kafka(JMX exporter)·Flink(메트릭 리포터)·Elasticsearch(모니터링 API) 지표는 **Prometheus·Grafana·Loki**(로컬 개발 + GKE 세션 한정, 자체호스팅이므로 관리형 지표만으로는 스트림 엔진 내부 상태 파악이 부족)로 보강 — v1.0(관리형 Dataflow만으로 충분)에서 스코프 확대.
- Logs: 구조화 JSON + correlation id(=event_id). DLQ·체크포인트 지연 알림은 Prometheus Alertmanager 또는 Cloud Monitoring 알림 정책.
- **핵심 모니터링 항목(대시보드 청사진)**:

| 항목 | 메트릭 | 경보 임계 |
|---|---|---|
| 수집 백로그 | Kafka consumer group lag(`records-lag-max`) | 10분 연속 증가 |
| 파이프라인 지연 | Flink 체크포인트 소요시간(`lastCheckpointDuration`)/워터마크 지연 | 체크포인트 > 60초 소요 또는 워터마크 지연 > 5분 |
| 유실 감시 | DLQ 메시지 수(`telemetry.dlq` + GCS `dlq/es/` 오브젝트 수) | > 0 (즉시) |
| 서빙 지연 | ES 검색 p99(부하시험 클라이언트 계측 + Kibana monitoring) | > 300ms |
| 품질 게이트 | dbt test 실패 수·store_failures 행 수 | > 0 |
| 비용 가드 | GCP 일일 지출(Budget alert) | > $10/일 |

### 10.3 Resilience
- Dead-Letter Queue(무손실), 재시도+백오프+jitter, 백프레셔(Flink 자연 백프레셔 — 체크포인트 배리어가 느린 오퍼레이터에서 지연), 외부 호출은 트랜잭션 밖(참고: DB 트랜잭션에 네트워크 호출 결합 금지).

### 10.4 Privacy
- 시뮬/공개 데이터 사용으로 PII 최소화. 실데이터 확장 시 위치정보 최소수집·보존정책 수립.

### 10.5 CI/CD (GitHub Actions)

| 트리거 | 파이프라인 단계 |
|---|---|
| PR | ① Java 단위 테스트(Flink 함수/오퍼레이터) + Python 린트/테스트 ② dbt `parse`+`compile`(SQL 유효성) ③ Terraform `fmt`+`validate`+`plan`(dry-run) |
| `main` push | 위 전체 + ④ **Flink 잡 JAR 빌드**(Docker 이미지 → Artifact Registry, 잡 아티팩트 → GCS) ⑤ 생성기 컨테이너 빌드·푸시 ⑥ Kafka/ES manifest(Helm/Kustomize) 검증 |
| 수동(workflow_dispatch) | ⑦ Terraform `apply`(세션/캠페인 up·down — §9.1 운영 모델의 실행 수단) ⑧ dbt seed/run 배포 ⑨ Flink 잡 제출(REST API, Airflow 트리거와 동일 경로) |

- 배포 원칙: **모든 클라우드 리소스 변경은 Terraform 경유**(콘솔 수동 변경 금지 — §8.1 토픽·ACL 관리 포함). 세션 기반 운영의 up/down도 동일 워크플로.

---

## 11. Architecture Decisions (ADR)

> **v2.0은 ADR 전면 re-baseline이다**(v1.0 대비 아키텍처 전환에 따른 결정 재도출). ADR-002/003/005/006/007/009는 v1.0과 **동일 번호이나 결정 내용이 갱신·대체**됨 — v1.0 원문은 git 히스토리를 참조한다. 매핑 요지: v1.0 ADR-009(오케스트레이션 하이브리드 운영 모델)는 v2.0에서 별도 ADR 없이 **§7.4/§12.7로 강등**(로컬 Airflow로 단순화)되었고, 번호 ADR-009는 v2.0에서 **Kafka HA 범위** 결정으로 재사용된다. 아래 각 ADR의 Context에 v1.0 대비 변경/재사용 근거를 명시한다 — 모든 내부·외부(README) 참조는 이 매핑과 일치해야 한다.

### ADR-001: 하이브리드 언어 전략 (Java/Flink + Python/SQL 글루)
- **Status**: Accepted
- **Context**: DE 생태계에서 오케스트레이션(Airflow)·변환(dbt/SQL)·품질은 Python/SQL이 표준이고, 고throughput·exactly-once 스트림 처리는 JVM 엔진(Flink/Kafka)이 강점이다. 지원자는 Java/Spring 배경(ecommerce-microservices)과 Python 배경(AutoNotify)을 모두 보유. 채용 공고는 메가존/현대차가 Python·SQL·Airflow·BigQuery를, 카카오뱅크가 실시간·exactly-once(JVM 스트리밍)를 요구.
- **Decision**: 역할 분리형 하이브리드 — **스트림 처리 코어는 Java(Apache Flink)**, **글루·오케스트레이션은 Python(Airflow, 생성기)**, **변환은 SQL(dbt)**. v1.0의 Java+Beam/Dataflow에서 **Java+Flink(self-host)** 로 전환(ADR-005).
- **Consequences**:
  - Positive: 세 공고의 요구 표면을 합집합으로 커버, JVM 스트리밍 강점 + Python/SQL baseline 동시 증명, 자체 운영 JVM 클러스터(Flink) 관리 역량까지 추가로 시연.
  - Negative: 다언어 + self-host 클러스터로 운영 복잡도 증가 → Java 컴포넌트를 Flink 잡 하나로 집중하고 MVP/스트레치 분리(§13)로 완화.
  - Neutral: JVM 워밍업은 long-running 스트리밍 잡에서 amortize되어 비이슈.

### ADR-002: 수집 = Apache Kafka self-host (vs Pub/Sub)
- **Status**: Accepted
- **Context**: v1.0은 GCP 네이티브·서버리스 이점을 우선해 Pub/Sub을 채택했다. 재검토 결과, 포트폴리오 목표가 "자체운영 스트리밍 인프라 시그널"(카카오뱅크 등 핀테크 실시간 스택 정조준)로 명확해졌고, 3rd-party 관리형(Confluent Cloud)은 GCP 무료 크레딧 미적용이라 self-host가 유일한 예산 내 경로다(호스팅 리서치 §서두).
- **Decision**: **Apache Kafka self-host**를 코어 수집으로 채택 — **KRaft**(ZooKeeper 없음, [Upgrading — Apache Kafka](https://kafka.apache.org/40/getting-started/upgrade/)), 공식 `apache/kafka` 이미지, Strimzi 등 오퍼레이터 미사용(단일 호스트 3-broker엔 불필요), 단일 호스트에 브로커 3개(GKE StatefulSet `replicas:3` 권장, ecommerce-microservices 선례 재활용). Pub/Sub은 기각 — GCP 관리형 대안으로 검토했으나 자체운영 스트리밍 시그널을 위해 Kafka를 채택한다(§12.3).
- **Consequences**:
  - Positive: Kafka 파티션·컨슈머 그룹·복제(RF/ISR) 운영 지식 직접 증명, 3rd-party Marketplace 크레딧 제약 회피, Flink KafkaSource와의 생태계 궁합(체크포인트 오프셋 통합, §6.4.1).
  - Negative: at-least-once라 소비자 idempotency 필요(Flink `keyBy` dedup으로 대응) — v1.0과 동일한 트레이드오프. 브로커 운영·모니터링(§10.2) 부담 신규 발생.
  - Neutral: 단일 호스트 3-broker는 broker-level 복제만 시연 — 인프라 HA(존/호스트 SPOF)는 스코프 밖(ADR-009).

### ADR-003: Bronze+Silver = Iceberg(Flink 싱크), Gold = BigQuery(BigLake)
- **Status**: Accepted
- **Context**: v1.0은 Bronze만 Iceberg(BigLake Metastore), Silver/Gold는 BigQuery 네이티브였다. 자체호스팅 전환으로 Flink가 Bronze/Silver 양쪽에 직접 쓸 수 있게 되면서, Silver까지 오픈포맷으로 옮기면 로컬 테스트 커버리지가 넓어지고(ADR-011) BigQuery 의존이 Gold(분석/ML) 층으로 축소된다.
- **Decision**: **Bronze + Silver = Apache Iceberg**(Flink 네이티브 Iceberg 싱크, GCS). **Gold = BigQuery** — dbt가 **BigLake 외부테이블**로 Silver Iceberg를 조회해 생성. Delta Lake/Hudi/BigQuery-native는 기각 유지(§12.4).
- **Consequences**:
  - Positive: 오픈 포맷·time travel·스키마 진화가 Bronze+Silver 전체로 확대, 엔진 비종속(Flink/dbt/DuckDB 모두 직접 조회 가능), BigQuery 스토리지·컴퓨트 비용이 Gold로 축소(§9.1).
  - Negative: BigLake 외부테이블은 read-only라 dbt의 Gold 생성이 "BigQuery가 Iceberg를 조회하는" 간접 경로 — 관리형 BigQuery-native 테이블(DML 직접 가능) 대비 한 홉 추가.
  - Neutral: Iceberg 카탈로그(로컬 Hadoop catalog, prod BigLake metastore/Lakehouse runtime catalog의 Iceberg REST catalog 엔드포인트)는 §16.1 로컬↔prod 전환 시 `catalog-impl`·`warehouse`·인증 설정만 교체.

### ADR-004: Polyglot 저장소 역할 분리 (정본 vs 서빙)
- **Status**: Accepted
- **Context**: 실시간 서빙(ES)만으로는 유실·재색인 시 원본 복구가 안 되고 이력 분석이 약하다. 반대로 웨어하우스(BigQuery)만으로는 저지연 단건·지리 조회가 느리다. "ES만 쓰면 정합성이 불안하니 RDB가 필요하지 않냐"는 질문의 실제 답은 저장소 종류가 아니라 파이프라인 보장이다. **v2.0에서도 이 원칙은 변경 없음** — 정본이 Bronze/Silver Iceberg로 이동했을 뿐 역할 분리 구조는 동일.
- **Decision**: 역할별 polyglot — Bronze+Silver(Iceberg)=정본, Gold(BigQuery)=분석 정본, Elasticsearch=**재구성 가능한 서빙 사본**(정본 아님), (선택) Cloud SQL=차량 레지스트리/멱등성 inbox/CDC 데모. 유실·정합성은 Bronze 불변 + Flink 체크포인트 exactly-once dedup + DLQ + 재처리로 보장.
- **Consequences**:
  - Positive: 각 저장소가 강점 워크로드만 담당, ES 장애가 정본에 영향 없음(재색인 복구), BigQuery≠RDB 특성(파티션/클러스터)로 비용·성능 제어.
  - Negative: 저장소 3~4종 운영·동기화 복잡도 → 단일 Flink 잡 Fork + IaC로 완화.
  - Neutral: 트랜잭션 관계 데이터는 소규모라 Cloud SQL은 선택 트랙으로 남김.

### ADR-005: 처리 = 네이티브 Apache Flink (vs Dataflow/Spark)
- **Status**: Accepted (v1.0 [ADR-005 Kappa]/§12.2 Dataflow 채택 결정을 **뒤집음**)
- **Context**: v1.0은 "GCP 네이티브 우선"으로 완전관리형 Dataflow(Apache Beam)를 채택하고 self-host Flink는 "Dataproc 선택적 컴포넌트, 운영 부담" 근거로 기각했다(구 §12.2). 재검토 결과, 포트폴리오 우선순위가 "관리형 서비스 사용 경험"에서 "스트림 엔진 자체 운영·튜닝 역량"으로 이동했고, Flink는 Kafka와 함께 업계 표준 self-host 스트리밍 스택이다.
- **Decision**: **네이티브 Apache Flink self-host**(JobManager+TaskManager, RocksDB state backend)를 스트림 처리 코어로 채택. Dataflow/Beam은 완전 제거. API = **DataStream + Flink SQL**. Spark Structured Streaming은 계속 기각(micro-batch 지연 하한이 G-3와 상충, §12.2).
- **Consequences**:
  - Positive: 체크포인트·상태 백엔드·오퍼레이터 체이닝 등 Flink 내부 튜닝 역량 직접 증명, Kafka와의 소스 오프셋 체크포인트 통합이 자연스러움([Checkpointing — Apache Flink](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/checkpointing/)).
  - Negative: 클러스터 상시 운영 부담(오토스케일·장애 복구를 직접 관리, v1.0 Dataflow는 완전관리형이라 없었던 부담) — GKE Deployment + 고정 TaskManager 수로 스코프 제한(§5.3).
  - Neutral: v1.0의 Beam Deduplicate는 Flink `keyBy`+`ValueState` TTL로 1:1 대체(§6.4.1) — 개념은 동일, 구현만 전환.

### ADR-006: exactly-once = Flink 체크포인트 + Kafka 오프셋 + Iceberg 2PC + ES 멱등
- **Status**: Accepted
- **Context**: v1.0의 ADR-006은 "ES 싱크 = 코어 잡 ElasticsearchIO 직접 write" 결정이었다. v2.0은 exactly-once 메커니즘 자체가 Dataflow 내장 기능(§6.4.1 구 버전)에서 Flink 체크포인트 기반으로 전환되므로, 이 ADR을 **exactly-once 경로 전체**를 다루도록 재정의한다(ES 멱등 결정은 유지·포함).
- **Decision**: exactly-once는 4단으로 구성한다 — ① Flink 체크포인트(Chandy-Lamport 비동기 배리어, [Fault Tolerance — Apache Flink](https://nightlies.apache.org/flink/flink-docs-stable/docs/learn-flink/fault_tolerance/))가 Kafka 소스 오프셋을 스냅샷, ② `keyBy(event_id)`+상태 TTL이 재전달 중복 제거, ③ Iceberg 싱크는 체크포인트 완료 시점에 **2PC 원자 커밋**([Flink Connector — Apache Iceberg](https://iceberg.apache.org/docs/latest/flink-connector/)), ④ ES는 `doc_id=event_id` 멱등 upsert(단일 일반 인덱스, data stream 기각 — §6.8). 매핑(geo_point)은 사전 index template로 제어, 보존은 delete-by-query.
- **Consequences**:
  - Positive: 클러스터 1개(Flink)로 비용·운영 최소, Kafka/Iceberg/ES 세 이질적 시스템에 걸친 exactly-once 서사를 자체 구현으로 증명(관리형 Dataflow의 "블랙박스 exactly-once"보다 시그널이 강함).
  - Negative: 체크포인트 튜닝(간격·타임아웃·상태 백엔드) 실패 시 지연·중복 위험이 v1.0(관리형)보다 직접적 — 60초 체크포인트 간격을 보수적 시작값으로 채택, §15 부하시험에서 보정.
  - Neutral: **잔여 리스크**: in-job 다중 싱크 결합(R-4) — ES 전용 잡 분리를 검토했으나 상시 클러스터 2개 비용(§9.1)으로 기각하고, 장애 격리는 ES DLQ shed(`dlq/es/`)로 확보.

### ADR-007: 인프라 = GKE/GCE 자체호스팅 (vs 완전관리형)
- **Status**: Accepted
- **Context**: v1.0의 ADR-007은 "생성기 런타임 = 로컬+Cloud Run Jobs" 주제였다. v2.0은 Kafka+Flink+ES 클러스터 전체를 자체호스팅으로 전환하면서 **인프라 배치 방식 자체**가 신규 핵심 결정이 되어 이 ADR 번호를 재사용한다(생성기 런타임 결정은 §5.3·§7.1로 이동, ADR 승격 해제 — 비용 임팩트가 작아 별도 ADR 불필요). Confluent Cloud·Elastic Cloud 등 3rd-party 관리형은 GCP 무료 크레딧 Marketplace 제한에 걸려 예산 내 불가능하다([GCP 무료 크레딧 제한](https://docs.cloud.google.com/free/docs/free-cloud-features)).
- **Decision**: Kafka+Flink+Elasticsearch는 **GKE(권장) 또는 GCE self-host**로 배치 — 1st-party 컴퓨트라 개인 크레딧이 커버한다. 비용 단위는 **node-hours**(§9.1)로 관리형 세션비 모델을 대체하고, 상시 가동 대신 **캠페인 stop/start**(Terraform up/down)로 크레딧을 통제한다.
- **Consequences**:
  - Positive: 인프라(K8s/VM) 운영 역량 직접 증명, 3rd-party Marketplace 크레딧 제약 완전 회피, 비용이 관리형(Elastic Cloud $99+/월) 대비 크게 낮아짐(§9.1, ~$26–29/월 세션 기준).
  - Negative: 3개 self-host 클러스터(Kafka/Flink/ES) 운영 복잡도 — 장애 대응·튜닝·업그레이드를 직접 부담(§13 R-6, MVP/스트레치 분리로 완화).
  - Neutral: GKE 클러스터 관리비($0.10/h)는 구글의 월 $74.40 무료 크레딧으로 사실상 상쇄(§9.1).

### ADR-008: 직렬화 포맷 = Avro (vs Protobuf, JSON) + Kafka 스키마 운영
- **Status**: Accepted
- **Context**: v1.0은 Pub/Sub 스키마 검증(Avro/Protobuf만 지원, JSON Schema 미지원)을 근거로 Avro를 채택했다. v2.0은 전송 계층이 Kafka로 바뀌면서 "Pub/Sub 스키마 검증 GA" 근거는 사라지지만, Avro는 Kafka 생태계(Confluent/OSS Schema Registry)와 DE 생태계(Iceberg/Flink/BigQuery) 양쪽에서 여전히 표준이다.
- **Decision**: 직렬화 포맷으로 **Avro(binary)** 를 계속 채택한다(`schemas/telemetry-event.avsc`, `schemas/dlq-envelope.avsc` — **스키마 파일 변경 없음**). 스키마 검증은 **별도 Schema Registry self-host를 옵션으로 남기고**, 기본은 **스키마 파일 + 클라이언트측 Avro 검증**으로 단순화한다(§8.1) — Pub/Sub 스키마 리비전 GA 기능이 없어지는 대신 Terraform으로 스키마 파일 버전을 관리.
- **Consequences**:
  - Positive: Iceberg/Flink/BigQuery 생태계 표준 포맷 유지로 커넥터 친화적, 스키마를 `schemas/*.avsc`로 코드와 분리해 버전 관리(변경 없음).
  - Negative: Pub/Sub의 서버측 스키마 검증·리비전 관리(최대 20개 자동 보관) GA 기능을 잃고 클라이언트측 검증으로 대체 — 검증 누락 리스크는 CI(§10.5 PR 단계 스키마 lint)로 보완.
  - Rejected: **Protobuf** — 분석계(BigQuery/dbt/Iceberg) 친화성이 Avro보다 낮고 코드젠 부담이 큼. **JSON** — 페이로드가 Avro binary 대비 비대해 처리량·비용에 불리.

### ADR-009: Kafka HA 범위 — broker-level 복제·failover (vs 인프라 HA)
- **Status**: Accepted
- **Context**: v1.0의 ADR-009는 "오케스트레이션 하이브리드 운영 모델"이었다. v2.0은 오케스트레이션이 로컬 Airflow로 단순화되며 별도 ADR이 불필요해지고(§7.4에 설계 기록), 대신 **Kafka 장애 대응 범위를 명확히 정의하는 결정**이 신규로 필요해 이 번호를 재사용한다. 사용자 확정 스코프: 장애 단위 = broker 프로세스(pod/컨테이너) 죽음이며, 호스트/존 장애는 대상이 아니다(호스팅 리서치 §4).
- **Decision**: **단일 머신**(GKE StatefulSet `replicas:3` 또는 GCE VM 1대 docker-compose 3컨테이너)에 브로커 3개를 배치하고, `replication.factor=3`/`min.insync.replicas=2`/`acks=all`/`unclean.leader.election.enable=false`로 **broker-level 복제·failover**만 보장한다. 존 분산·다중 VM·rack awareness·MIG는 **드롭**(오버스코프). 데모는 브로커 1개 `kill` → 리더 재선출 → 유실 0·계속 처리로 시연(§5.4).
- **Consequences**:
  - Positive: 1머신 3-broker로 HA 데모 요구를 저비용으로 충족, Strimzi 등 오퍼레이터 없이 ecommerce-microservices 선례 재활용으로 구현 시간 절약.
  - Negative: 인프라 HA(존/호스트 SPOF)는 스코프 밖 — 채용 담당자에게 "broker-level 복제·failover 시연, 인프라 HA는 스코프 밖"으로 **정직하게 프레이밍**해야 함(README/면접 공통, 필수 문구).
  - Neutral: 브로커 2개 이상 동시 손실 시 ISR 부족으로 write가 거부되나(가용성 저하) 유실은 없음(§5.4).

### ADR-010: 이상탐지 = BigQuery ML (vs Elastic ML)
- **Status**: Accepted
- **Context**: v1.0은 Elastic ML(Elastic Cloud 관리형)을 이상탐지로 채택했다. v2.0에서 ES가 self-host **Basic tier**(무료)로 전환되며 Elastic ML은 Platinum 유료 기능이라 애초에 사용할 수 없다. 이상탐지 대상 데이터(급가속·과열·연비 패턴)의 정본은 이미 BigQuery Gold에 있어, 데이터를 옮기지 않고 그 자리에서 SQL로 학습·탐지하는 편이 자연스럽다(호스팅 리서치 §2).
- **Decision**: 이상탐지 학습 모델은 **BigQuery ML**(`ML.DETECT_ANOMALIES`, 시계열은 `ARIMA_PLUS`, §6.8 `gold.model_speed_anomaly`)로 채택. 규칙 기반 임계(급가속·과열 등)는 Gold 집계(결정론적, ML 아님)가 계속 담당하고, 실시간 임계 알림은 **Kibana Alerting**(Basic 무료)이 담당. Elastic ML은 드롭.
- **Consequences**:
  - Positive: self-host Basic tier 제약과 충돌 없음, 데이터 이동 0(Gold에 이미 존재), 크레딧으로 영구 유지(30일 trial 제약 없음), "SQL-native ML을 dbt Gold에 통합"이라는 채용 시그널.
  - Negative: Elastic ML의 이상 탐지 UI(Kibana 내장 애니멀리 뷰)는 사용 불가 — Kibana Alerting(임계 규칙)으로 실시간 경보만 대체, 학습 기반 이상탐지 결과는 BQ ML 쿼리/대시보드로 별도 시각화.
  - Neutral: 3층 역할 분담(규칙 기반=Gold 집계, 학습 기반=BQ ML, 실시간 알림=Kibana Alerting)으로 책임이 명확히 분리(호스팅 리서치 §2).

### ADR-011: 로컬 테스트 전략 — Iceberg 중심 로컬 E2E + BigQuery 3층 대체
- **Status**: Accepted
- **Context**: v1.0은 Pub/Sub emulator(스키마 검증 미지원)·로컬 Iceberg(Bronze만)·BigQuery(로컬 대체 없음, dev GCP 샌드박스 의존)로 로컬 테스트 커버리지가 제한적이었다. v2.0은 Kafka·Flink·ES·Iceberg가 전부 컨테이너로 실행 가능해 커버리지를 크게 넓힐 수 있다.
- **Decision**: **Kafka→Flink→Iceberg(Bronze+Silver)→ES 전 구간을 로컬 E2E로 검증**한다(로컬 Iceberg 카탈로그 = Hadoop/REST + MinIO, DuckDB/pyiceberg로 데이터 검증). **BigQuery만 로컬 대체가 없어 3층으로 분리 대응**:
  1. **dbt/SQL 로직 검증** = **DuckDB(`dbt-duckdb`)**/dbt unit test — Silver Iceberg 스냅샷을 DuckDB Iceberg extension으로 로드해 Gold 모델 SQL을 로컬 실행([dbt-duckdb](https://github.com/duckdb/dbt-duckdb)).
  2. **DDL/쿼리 커버리지(부분)** = **`goccy/bigquery-emulator`**(Docker+Testcontainers) — BigQuery API 표면(DDL, 표준 쿼리)을 흉내내는 Go 구현 로컬 서버로 CI에서 기동([goccy/bigquery-emulator](https://github.com/goccy/bigquery-emulator)).
  3. **GEOGRAPHY·BQ ML·BigLake 통합**(에뮬레이터가 커버 못하는 영역) = **BigQuery Sandbox**(무료, 카드 불필요, [Try BigQuery using the sandbox](https://docs.cloud.google.com/bigquery/docs/sandbox))에서 통합 시험 — v1.0의 "dev GCP 샌드박스"보다 예산·계정 부담이 낮음(Sandbox는 결제 계정 자체가 불필요).
- **Consequences**:
  - Positive: BigQuery 의존이 Gold 층으로 축소된 것과 맞물려(ADR-003) 로컬 테스트 커버리지가 v1.0보다 넓어짐 — Kafka/Flink/Iceberg/ES는 100% 컨테이너 재현, BigQuery도 SQL 로직은 DuckDB로 대부분 커버.
  - Negative: 3층(DuckDB/emulator/Sandbox) 분리라 "완전히 동일한 엔진"으로 검증되지 않는 부분(BigLake 커넥션, BQ ML 실제 실행)은 Sandbox 통합 시험에서만 확인 가능 — CI 자동화는 DuckDB/emulator 층까지, Sandbox는 수동/주기 시험.
  - Neutral: `goccy/bigquery-emulator`는 SQLite 기반이라 ZetaSQL 표준 SQL 표면의 일부만 지원 — dbt 모델의 표준 집계·조인 검증에는 충분하나 GEOGRAPHY 함수·BQ ML은 Sandbox로 이관(§15).

---

## 12. Alternatives Considered

### 12.1 언어/클라우드 전략

| Alternative | Pros | Cons | Why Rejected |
|---|---|---|---|
| 올-자바 | JVM 스트리밍 강점 집중 | Airflow/dbt(Python/SQL) baseline 미증명, 생태계 역주행 | 메가존/현대차 요구(Python·SQL·Airflow) 미충족 |
| 올-파이썬 | 단일 언어 단순 | PyFlink는 얇은 드라이버, 고throughput·JVM 강점 미증명 | 카뱅 실시간 시그널 약함 |
| **Kafka + Flink(자체호스팅)** | 실시간 강력, 핀테크 정석, 자체운영 시그널 | 운영 부담↑(§13 R-6) | ✅ **v2.0 채택**(ADR-002·ADR-005, MVP/스트레치로 부담 완화) |
| Snowflake | 강력한 웨어하우스 | GCP 외부, 비용 | GCP·BigQuery 목표와 불일치 |

### 12.2 스트림 처리 엔진: 네이티브 Flink (vs Dataflow, Spark Structured Streaming)

| 대안 | 판정 | 근거 | 레퍼런스 |
|---|---|---|---|
| **Apache Flink(self-host)** | ✅ **v2.0 채택** | 체크포인트 기반 exactly-once를 자체 구현·튜닝(2PC Iceberg 싱크 포함)해 스트림 엔진 소유 역량을 직접 증명. Kafka와 소스 오프셋 체크포인트 통합이 자연스러움 | [Checkpointing — Apache Flink](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/checkpointing/) |
| Dataflow(Apache Beam) | ❌ 기각(v1.0 채택 → v2.0 뒤집음) | 서버리스 완전관리형은 운영 부담이 낮지만 "관리형 서비스 사용"에 그쳐 스트림 엔진 자체 운영 시그널이 없음 — 포트폴리오 목표가 자체운영 인프라 증명으로 이동(ADR-005) | [Exactly-once in Dataflow](https://cloud.google.com/dataflow/docs/concepts/exactly-once) |
| Spark Structured Streaming | ❌ 기각(v1.0과 동일 사유 유지) | micro-batch 엔진이라 지연이 배치 트리거 주기에 하한(공식 목표 최저 ~100ms), exactly-once는 멱등 싱크 설계에 의존 — 저지연 서빙(G-3) 요구와 상충 | [Structured Streaming Programming Guide](https://spark.apache.org/docs/3.5.8/structured-streaming-programming-guide.html) |

### 12.3 수집: Apache Kafka self-host (vs Pub/Sub)

| 대안 | 판정 | 근거 | 레퍼런스 |
|---|---|---|---|
| **Apache Kafka(self-host, KRaft)** | ✅ **v2.0 채택** | 자체운영 스트리밍 시그널, 3rd-party Marketplace 크레딧 제약 회피(1st-party 컴퓨트로 커버), Flink KafkaSource 체크포인트 통합 | [ADR-002](#adr-002-수집--apache-kafka-self-host-vs-pubsub) |
| Cloud Pub/Sub(v1.0 채택) | ❌ 기각(v2.0에서 뒤집음) | 완전관리형·서버리스 이점은 있으나 "GCP 관리형 대안으로 검토했으나 자체운영 스트리밍 시그널을 위해 Kafka 채택"(A.1 확정 결정) — 채용 시그널 우선순위 변경 | ADR-002 |

### 12.4 저장 포맷: Iceberg(Bronze+Silver, v2.0 확대) (vs Delta Lake, Hudi, BigQuery-native)

| 대안 | 판정 | 근거 | 레퍼런스 |
|---|---|---|---|
| **Apache Iceberg(GCS, Flink 네이티브 싱크)** | ✅ 채택(v1.0=Bronze만 → v2.0=Bronze+Silver로 확대) | 오픈 포맷·엔진 비종속, Flink `FlinkSink`가 체크포인트 단위 2PC 커밋 지원, BigLake로 BigQuery read 지원(Gold 생성 경로) | [Flink Connector — Apache Iceberg](https://iceberg.apache.org/docs/latest/flink-connector/), [Create Apache Iceberg external tables](https://docs.cloud.google.com/bigquery/docs/iceberg-external-tables) |
| Delta Lake | ❌ 기각(v1.0과 동일 사유 유지) | Databricks 색채가 짙은 포맷이고, BigLake 통합이 Iceberg 대비 약함 — BigQuery의 Delta 지원은 **read-only 외부 테이블**(DML·스트리밍 write 불가), Iceberg의 완전한 read/write와 비대칭. Flink Delta 커넥터도 Iceberg만큼 성숙하지 않음 | [BigQuery: Delta Lake tables](https://docs.cloud.google.com/bigquery/docs/create-delta-lake-table) |
| Apache Hudi | ❌ 기각(v1.0과 동일 사유 유지) | BigQuery/BigLake 통합이 hive-style copy-on-write 매니페스트 조회로 한정 — 네이티브 read-write 미지원, 운영 복잡도 큼 | [BigQuery: query open table formats](https://docs.cloud.google.com/bigquery/docs/query-open-table-format-using-manifest-files) |
| BigQuery-native 테이블(Silver) | ❌ 기각(v1.0 채택 → v2.0 뒤집음) | 오픈 포맷이 아님 — 엔진 종속, "Silver도 오픈포맷 backbone" 목표(ADR-003)와 불일치. 로컬 테스트 커버리지도 낮아짐(ADR-011) | ADR-003 |

### 12.5 실시간 서빙: Elasticsearch self-host (vs 관리형 Elastic Cloud, OpenSearch)

| 대안 | 판정 | 근거 | 레퍼런스 |
|---|---|---|---|
| **Elasticsearch(self-host, Basic tier)** | ✅ **v2.0 채택**(v1.0=Elastic Cloud 관리형 → self-host로 전환) | 라이선스 비용 0, GCP Marketplace 경유 3rd-party는 크레딧 미적용이라 self-host가 예산 내 유일한 경로. Kibana Maps는 Basic tier에 포함 | 호스팅 리서치 §1 |
| Elastic Cloud(관리형, v1.0 채택) | ❌ 기각(v2.0에서 뒤집음, trial 곁들이기만 유지) | 상시 가동엔 부적합($99+/월) — elastic.co 직접가입 14일 trial은 데모 곁들이기 옵션으로만 남김(GCP Marketplace 경유는 trial 미적용) | [Elastic Pricing FAQ](https://www.elastic.co/pricing/faq) |
| OpenSearch | ❌ 기각(v1.0과 동일 사유 유지) | 2021년 Elastic의 라이선스 변경(ALv2→Elastic License/SSPL)에 반발해 AWS가 포크한 프로젝트 — AWS/자체호스트 생태계 중심이라 채용 공고 타깃(Elastic Stack)과 어긋남 | [AWS: Stepping up for a truly open source Elasticsearch](https://aws.amazon.com/blogs/opensource/stepping-up-for-a-truly-open-source-elasticsearch/) |

### 12.6 변환: dbt (vs Dataform)

| 대안 | 판정 | 근거 | 레퍼런스 |
|---|---|---|---|
| **dbt** | ✅ 채택(변경 없음) | `dbt_utils` 등 패키지 생태계·커뮤니티가 크고 업계 표준 도구로 자리잡아 채용 시그널이 강함, 웨어하우스 비종속(v2.0에서는 BigLake 소스로 Iceberg까지 조회) | [dbt-core](https://github.com/dbt-labs/dbt-core), [dbt_utils](https://hub.getdbt.com/dbt-labs/dbt_utils/latest/) |
| Dataform | ❌ 기각(변경 없음) | BigQuery 네이티브·Google 인수 도구지만 독립 프로젝트로서 커뮤니티·채용 시그널이 dbt 대비 뚜렷이 약함(GitHub 활동·구인 공고 모두 낮음) | [Dataform (Google Cloud)](https://cloud.google.com/dataform) |

### 12.7 오케스트레이션: 로컬 Airflow (vs 세션형 Cloud Composer, Cloud Scheduler)

| 대안 | 판정 | 근거 | 레퍼런스 |
|---|---|---|---|
| **로컬 Docker Compose Airflow** | ✅ **v2.0 채택**(v1.0의 "로컬+세션형 Composer 하이브리드"에서 단순화) | Kafka/Flink/ES가 이미 self-host라 오케스트레이터도 self-host로 통일하는 편이 크레딧 절약·운영 일관성 측면에서 유리 — Composer 세션 기동의 GKE/GCE 대안 자체가 이미 존재해 하이브리드의 이점(관리형 신뢰성)이 상대적으로 작아짐 | §7.4 |
| 세션형 Cloud Composer(v1.0 하이브리드 구성요소) | ❌ 드롭(필요 시 재검토) | Small 환경비 $0.35/h 상시 가동 시 월 $252(+컴퓨트 별도)로 개인 크레딧을 단독 소진 — Kafka/Flink/ES가 이미 self-host 노드를 쓰고 있어 Airflow도 같은 노드군에 self-host하는 편이 일관적 | [Composer pricing](https://cloud.google.com/composer/pricing) |
| Cloud Scheduler(단순 cron) | ❌ 기각(변경 없음) | DAG 의존성 그래프·백필 기능 부재 — `dbt_hourly`→`bq_to_es_daily` 의존성(§7.4), `backfill_manual` 백필 요구를 충족 못함 | §7.4 |

---

## 13. Risk Register (선택)

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| R-1 | 다언어(Java/Python/SQL) 운영 복잡도 | Medium | Medium | Java는 Flink 코어에만 국한, 나머지 Python/SQL | {이름} |
| R-2 | 시뮬 데이터가 현실성 부족 | Medium | Low | comma2k19는 97GB·pose/GNSS/vision 중심 인지연구 데이터라 fleet OBD 시나리오에 과잉·부적합해 기각(§1.3) — [Kaggle Levin 실측 텔레메트리](https://www.kaggle.com/datasets/yunlevin/levin-vehicle-telematics)로 SUMO 물리 모델(속도·가속도·연료 파라미터)을 보정 | {이름} |
| R-3 | GCP 비용 초과 | Medium | Medium | 파티셔닝·시간가속·부하 상한 + 자체호스팅 node-hours 모델 + 캠페인 stop/start로 상시 비용 최소화(§9.1) | {이름} |
| R-4 | 단일 Flink 잡 다중 싱크 커플링 — 한 싱크(Iceberg/ES) 지연·장애가 체크포인트 정체로 전체 처리량 저하 | Medium | Medium | 싱크별 재시도 상한 + ES 실패는 DLQ로 shed(§5.2) + 체크포인트·백로그 지연 알림(§10.2), 임계 초과 시 잡 업데이트로 해당 싱크 우회 | {이름} |
| R-5 | Kafka 브로커 3개가 단일 호스트에 동거 — 호스트 자체 장애 시 3개 모두 손실(인프라 HA 아님, 정직한 한계) | Medium | Medium | README/면접에서 명시적으로 스코프 밖 선언(ADR-009), 존 분산은 백로그 항목으로만 보존(§18) | {이름} |
| R-6 | 3개 self-host 클러스터(Kafka/Flink/ES) 동시 운영 복잡도 — 장애 대응·튜닝·업그레이드를 관리형 대비 직접 부담 | High | Medium | **MVP(2주 핵심)/스트레치 분리**(§16)로 클러스터 안정화 순서를 명확히 하고, 스트레치(BQ ML·CDC) 미완료여도 MVP만으로 데모 성립 — 클러스터별 헬스체크·재기동 스크립트를 P1-P2에서 우선 구축 | {이름} |

---

## 14. Requirements Traceability (선택)

| Req ID | Requirement | Design Section | Test Case |
|---|---|---|---|
| G-1 | 무손실·effectively exactly-once(재전달 중복 차단) | §7.2, §10.3 | TC-DEDUP-01(TTL 내 재전달 시 중복 0 검증) |
| G-1 | event_id 발급 계약(유일·재시도 불변) | §6.2, §7.1 | TC-ULID-01(생성기 단위: 대량 발급 유일성 + 재시도 시 동일 이벤트 재사용·상이 이벤트 미재사용 — 위반 시 dedup이 정상 이벤트를 삭제하는 역설 차단) |
| G-1 | 불량 메시지 격리·재처리 | §6.7 | TC-DLQ-01(DLQ 격리 후 재발행 CLI로 재처리, 이중 처리 없음 검증) |
| G-1 | 유실 0 대사(reconciliation) | §15 | TC-RECON-01(항등식 `distinct_published = Silver_COUNT(DISTINCT event_id) + telemetry.dlq_distinct`, 정의는 §15) |
| G-2 | 처리량 5,000 rps sustained | §9, §15 | LT-LOAD-01(5,000 rps 부하 생성·측정) |
| G-3 | 서빙 p99 < 300ms | §5, §9 | LT-LOAD-01(위 부하시험에서 서빙 p99 동시 측정) |
| G-4 | 원본→Gold 데이터 품질 게이트(**스트레치/P5 게이트**, §16.1) | §7.3 | dbt test **error severity 전체 pass** + store_failures 0행(단 `unique(event_id)` warn tripwire 발동행은 별도 관측 지표로 집계 — 정상 동작이며 실패 아님, §6.4.1·§7.3) |
| G-5 | 피드백→설계 추적성 | §11 ADR | 문서 검사(피드백 항목 ↔ ADR/설계 섹션 링크 존재) |

> **스트레치 게이트 표기**: G-4(dbt 품질 게이트)와 BigQuery ML 이상탐지(NG-3, ADR-010)는 모두 **스트레치(P5) 게이트**다(§16.1 MVP/스트레치 구분) — MVP(P1~P4) 충족 목표집합에는 포함되지 않으며, 스트레치 미완료 상태에서도 코어 파이프라인(Kafka HA·Flink exactly-once·Iceberg·Kibana 지도)만으로 데모가 성립한다.

---

## 15. Testing Strategy

- **Unit**: 변환 로직·파서·Flink 함수/오퍼레이터(Java) 단위 테스트(Flink MiniCluster/`AbstractStreamOperatorTestHarness`) + **TC-ULID-01**(event_id 발급 계약 — 대량 발급 유일성·재시도 불변성, §6.2).
- **Integration — 로컬 3층 테스트(v1.0 대비 커버리지 확대, ADR-011)**:
  1. **Kafka→Flink→Iceberg→ES 전 구간**: Testcontainers로 로컬 Kafka(`apache/kafka` 공식 이미지, docker-compose)·로컬 Iceberg 카탈로그(Hadoop/REST + MinIO)·로컬 Elasticsearch를 기동해 **Flink 잡을 prod와 동일 코드로 실행**. DuckDB/pyiceberg로 Iceberg 테이블 내용 검증. 이 구간은 컨테이너만으로 완전 재현 가능 — v1.0의 "Pub/Sub emulator 스키마 검증 미지원" 한계가 소멸(§8.1).
  2. **dbt/SQL 로직**: **DuckDB(`dbt-duckdb`)** 로 Silver Iceberg 스냅샷을 로드해 Gold 모델 SQL·dbt unit test를 로컬 실행([dbt-duckdb](https://github.com/duckdb/dbt-duckdb)).
  3. **BigQuery DDL/쿼리(부분)**: **`goccy/bigquery-emulator`**(Docker+Testcontainers)로 CI에서 표준 쿼리 표면을 검증([goccy/bigquery-emulator](https://github.com/goccy/bigquery-emulator)).
  4. **GEOGRAPHY·BQ ML·BigLake 통합**: 로컬 대체가 없는 부분은 **BigQuery Sandbox**(무료, 카드 불필요, [Try BigQuery using the sandbox](https://docs.cloud.google.com/bigquery/docs/sandbox))에서 수동/주기 통합 시험.
- **E2E**: 생성기 → Kafka → Flink → Iceberg/ES → (BigLake) Gold/ES 핵심 플로우 1~2개.
- **Load / Performance (LT-LOAD-01 프로토콜, v1.0과 동일 — Flink/Kafka 기준으로 지표만 치환)**:
  1. **사전 캘리브레이션**: 생성기 vCPU당 달성 eps 실측 → 10x 배율 실현성 확정(미달 시 차량 수 상향/합성 병행, §7.1).
  2. **워크로드**: open-model 고정 rate 5,000 eps(백프레셔로 rate를 낮추지 않음 — coordinated omission 회피), 6시간 sustained.
  3. **서빙 p99 측정**: 색인 부하 진행 중에 **클라이언트측 계측**으로 대표 쿼리 2종 — ① 최근 5분 fleet 위치 geo bounding-box 쿼리(Kibana Maps 백엔드 쿼리와 동형) ② 단일 차량 최근 1시간 드릴다운 — 를 일정 rate로 발사해 p99 산출(HdrHistogram 기록).
  4. **sustained 판정 기준**: 6시간 동안 Kafka consumer lag 비증가 + Flink 체크포인트 소요시간 안정(<체크포인트 간격의 50%) + 워터마크 지연 < 5분(§10.2 지표).
  5. **유실 0 대사(TC-RECON-01)**: 명시 항등식 — `distinct_published = Silver_COUNT(DISTINCT event_id) + telemetry.dlq_distinct(검증실패 3종만: PARSE_FAILURE/SCHEMA_VALIDATION_FAILURE/BUSINESS_RULE_FAILURE)`. `distinct_published`은 생성기 발행 카운터를 **distinct `event_id` 기준**으로 집계한 값(publish 재시도 attempt 수가 아님, §6.2 event_id 계약). `SINK_WRITE_FAILURE`는 검증 통과 후 이미 Iceberg(Bronze/Silver)에 도달한 이벤트라 대사에서 **제외**한다(포함 시 이중계산, §6.7). Bronze는 이 항등식에 들어가지 않고 별도 "**중복 관측**" 지표(raw count − distinct count)로 분리 관찰한다(§6.4).
- **Chaos**: **Kafka 브로커 1개 kill**(ADR-009 데모 겸용) + Flink TaskManager kill·의존성 중단 시 체크포인트 복구·DLQ·재처리 검증 + **지연 주입**(생성기 delay 옵션으로 일부 이벤트를 수 분~수 일 늦게 발행 — event_time=wall-clock 정의상 자연 발생하지 않는 late 경로를 인위 재현, §6.4.1 검증).

---

## 16. Rollout / Deployment Plan

### 16.1 Phased Rollout (정본 = README 5-Phase 로드맵, MVP/스트레치 재분리)

**MVP(2주 핵심, P1~P4 상당)**: Kafka HA(브로커 kill 데모) + Flink exactly-once + Iceberg(Bronze/Silver) + Kibana 지도 = 돌아가는 end-to-end. 스트레치 미완료여도 데모 성립.
**스트레치**: BigQuery ML, Gold 집계(우선 2~3개), CDC(Phase 3 확장).

| Phase | 내용 | 환경 | 구분 |
|---|---|---|---|
| **P1 수집** | 생성기/리플레이 → Kafka `telemetry.raw`, Avro 스키마 파일 등록·클라이언트 검증 | 로컬(하단 스펙) → dev GKE/GCE Kafka | MVP |
| **P2 정제(Bronze/Silver)** | Flink Stream Processor(다중 싱크)·DLQ·`keyBy` dedup — **착수 전: GCS fleet 정의 CSV 배치 완료(생성기와 동일 소스, §7.2 broadcast state 전제)**. `dim_vehicle`/`dim_geofence` dbt seed는 Gold 조인 검증용(P5)이라 P2 착수 조건이 아님 | 로컬 Flink MiniCluster → dev GKE/GCE Flink(수 노드) | MVP |
| **P3 서빙** | ES 클러스터 기동, Kibana Maps, `telemetry-fleet` 인덱스 색인 | 로컬 Docker ES → dev GKE/GCE ES(Basic) | MVP |
| **P4 Kafka HA 데모** | 3-broker 배포, 브로커 kill 시연, RF=3/ISR=2 검증 | dev GKE/GCE Kafka(3-broker) | MVP |
| **P5 집계(Gold)+BQ ML** | dbt seed/모델(BigLake 경유)·품질 테스트, Airflow DAG, `model_speed_anomaly` | 로컬 Airflow(개발) / 세션 시 GKE in-cluster Airflow(§5.3) + BigQuery Sandbox/dev | 스트레치 |
| **P6 부하·검증** | 캘리브레이션 → 5,000 eps LT-LOAD-01·SLO 검증 | Cloud Run Jobs(생성기) + GKE/GCE 세션 | 스트레치 |
| (P6 이후 확장) | Cloud SQL/CDC — Debezium 아웃박스 데모(§4.1·§6.5) | 선택 확장 트랙 | 스트레치 |

- P1 착수 전 체크: 아키텍처 다이어그램(PNG) v2.0 재생성 — **미완료, P1 착수 전 백로그**(§5.2 텍스트 다이어그램이 v2.0 잠정 정본, arch 리뷰 m3).

**P1–P2 로컬 실행 스펙:**
- 러너: Flink **MiniCluster**(prod와 동일 파이프라인 코드).
- Kafka 로컬: 공식 `apache/kafka` 이미지 docker-compose 3컨테이너(KRaft) — prod와 동일 이미지·모드라 로컬-dev 경로 차이 없음(§8.1).
- Bronze/Silver 로컬: Iceberg **Hadoop catalog**(로컬 파일시스템 `./warehouse`, MinIO로 GCS 흉내) — prod 전환은 카탈로그 설정을 다음 3개로 교체(코드·파이프라인 로직은 동일):
  - `catalog-impl`: `org.apache.iceberg.hadoop.HadoopCatalog` → **BigLake metastore(Lakehouse runtime catalog) Iceberg REST catalog**(`catalog-type=rest`)
  - `warehouse`: `./warehouse`(로컬FS) → `gs://fleetsentinel-{bronze,silver}`(GCS)
  - 인증: 로컬은 MinIO access key/secret → prod는 GCP 서비스 계정(`sa-flink`, §5.3) + REST catalog credential vending([About the Lakehouse runtime catalog](https://docs.cloud.google.com/lakehouse/docs/about-lakehouse-catalogs))
- ES 로컬: Docker 단일 노드, index template·매핑 동일.
- BigQuery: 로컬 대체는 DuckDB(`dbt-duckdb`)/`goccy/bigquery-emulator` 2층, 완전 통합 시험은 **BigQuery Sandbox**(§15). 로컬 P2 완료 기준은 Iceberg(로컬)+ES(로컬 Docker) 싱크까지. **P2의 enrich·미등록 판정은 로컬/prod 공통으로 GCS fleet CSV 직접 로드**(§7.2 — BigQuery 불필요; 로컬은 로컬 파일시스템/MinIO로 대체).

### 16.2 Data Migration
- 스키마 진화는 Iceberg로 하위호환 처리(dual-write 불필요) — Bronze+Silver 모두 Iceberg라 v1.0보다 진화 범위가 넓어짐.

### 16.3 Rollback Plan
- 트리거: DLQ 급증 / 품질 테스트 실패 / 처리량 붕괴 / 체크포인트 반복 실패. 절차: Flink 잡 버전 롤백(이전 체크포인트/세이브포인트에서 재기동), 문제 배치 재처리.

---

## 17. Glossary

| Term | Definition |
|---|---|
| Medallion | Bronze/Silver/Gold 3계층 데이터 정제 아키텍처 |
| Exactly-once | 중복·유실 없이 정확히 한 번 반영되는 처리 보장 |
| DLQ | Dead-Letter Queue (처리 실패 메시지 격리) |
| Fork(싱크) | 동일 스트림을 단일 Flink 잡 안에서 복수 싱크(Iceberg Bronze·Iceberg Silver·ES)로 분리 적재(다중 싱크) |
| Coordinated omission | 부하 생성기가 stall 중 요청 누락으로 지연을 과소측정하는 벤치마크 오류 |
| KRaft | Kafka Raft — ZooKeeper 의존을 제거하고 Kafka 자체 Raft 합의로 메타데이터를 관리하는 모드([KIP-500](https://developer.confluent.io/learn/kraft/)) |
| 체크포인트(Flink) | Flink가 주기적으로 오퍼레이터 상태·소스 오프셋을 durable storage에 스냅샷해 장애 복구에 사용하는 메커니즘(§6.4.1) |
| BigLake | BigQuery가 GCS 위 Iceberg/Delta 등 오픈 테이블 포맷을 외부테이블 또는 관리형 테이블로 조회·통합하는 계층 |

---

## 18. Appendix (선택)

- A. 아키텍처 다이어그램 원본: [`diagrams/system-architecture.excalidraw`](diagrams/system-architecture.excalidraw) (Excalidraw) — **PNG는 P1 착수 전 백로그로 재생성 예정**(§5.2 텍스트 다이어그램이 v2.0 잠정 정본, arch 리뷰 m3).
- B. Capacity 추정(Little's Law: concurrency = RPS × latency)
  - 목표 처리량 G-2 = 5,000 rps sustained. 인플라이트 처리 지연 가정 0.2s — **근거 없는 초기 가설임을 명시**한다(네트워크 I/O·직렬화·다중 싱크 부하로 변동). LT-LOAD-01 사전 캘리브레이션(§15)에서 소규모 부하로 실측해 보정하는 것이 전제이며, 이 값이 틀리면 TaskManager 수 추정도 함께 보정된다.
  - Little's Law: L = λ × W = 5,000 rps × 0.2s ≈ **1,000 동시 이벤트**(concurrency).
  - Flink TaskManager: `e2-standard-4`(4 vCPU/16GB) 기준 TaskManager당 처리 가능한 동시 이벤트를 수백 단위로 보수적으로 잡으면 **TaskManager 2~4대**로 피크(5,000 eps, §7.1) 커버 추정 — 실측 병렬도 범위는 §15 부하시험에서 검증.
- C. Open Questions: **0건** — comma2k19 데이터 포함 여부는 기각으로 종결(§1.3, §13 R-2), Kafka는 v2.0에서 코어 채택으로 종결(§12.3, 구 "대체 트랙" 논의 해소). A(다이어그램 PNG 재생성)는 **P1 착수 전 백로그로 재오픈**(§5.2 텍스트 다이어그램이 잠정 정본, arch 리뷰 m3) — 설계 확정이 아니라 산출물 갱신 작업이라 Open Questions 집계에는 포함하지 않는다. B(위 capacity 추정)는 참고 항목으로 유지.