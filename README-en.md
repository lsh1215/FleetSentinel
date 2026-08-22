# FleetSentinel

[한국어](README.md) | [English](README-en.md)

A data-engineering platform that ingests → refines → analyzes **fleet-scale real-time vehicle telemetry**. Built around a self-hosted OSS streaming lakehouse (Kafka → Flink → Iceberg/BigQuery) and a Medallion (Bronze/Silver/Gold) refinement layer, it turns millions of raw telemetry events into trustworthy analytical data, and serves real-time map visualization and anomaly detection through Elasticsearch (self-host). It uses a **hybrid language split — Java (Flink) for high-throughput stream processing, Python for glue/orchestration, SQL for transforms.**

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

> **Status:** 🔄 **v3.0 redesign in progress — pivoting to autonomous-driving multimodal data.**
>
> The content below reflects **v2.0 (vehicle OBD telemetry)** and is kept as history. The project is
> being redesigned as a platform that ingests and monitors **multimodal sensor data** (camera, LiDAR,
> radar, CAN) from autonomous vehicles/robots and curates it into ML training sets.
>
> - **Current data design → [docs/data-design-v3.md](docs/data-design-v3.md)** (source of truth, Korean)
> - Design history → [docs/sdd.md](docs/sdd.md) (v2.0; §6 superseded by the above)
> - Runbook → [RUN.md](RUN.md)
>
> The v2.0 implementation (synthetic generator, Flink job, OBD serving layer) was removed in the pivot.
> The verified infrastructure layer (Kafka 3-broker HA, Flink, Iceberg, ES/Kibana) and Maven pins remain.

> **Motivation (Prior Art).** This project is a **personal extension** of the Qualcomm-partnered capstone **[AutoNotify](https://github.com/Qualcomm-Capstone)** (an On-Device-AI real-time speeding-detection & notification system) into the data-engineering domain. It started from feedback a Qualcomm engineer gave at the capstone presentation — _"The edge side, catching events one vehicle at a time, is well built. But once you take this to real fleet scale — hundreds or thousands of vehicles streaming every second — the bottleneck moves from the model to the ingestion, storage, and refinement pipeline. Handling that stream without loss or duplication is the genuinely hard part."_ — which motivated generalizing AutoNotify's edge → MQTT event architecture into a **platform that handles continuous telemetry across an entire fleet**. (Qualcomm was not involved in this extension; the extension's design and implementation were done solo.)

## Overview

Data engineering is not about reducing data volume — it is about refining **raw → trusted → usable**. FleetSentinel preserves millions of raw telemetry events losslessly (Bronze), strips duplicates/nulls/outliers to make them trustworthy (Silver), aggregates them into purpose-built metrics (Gold), and serves the result through real-time dashboards and anomaly detection. Where AutoNotify processed a **single vehicle's event**, FleetSentinel generalizes it to a **continuous stream across the whole fleet**, focusing on how latency, loss, and duplication are handled at scale.

## Language Strategy (Hybrid)

In the DE ecosystem, orchestration/transform/quality are Python/SQL by convention, while high-throughput, exactly-once stream processing is where JVM engines excel. Each layer is placed on the **language that fits its rationale**.

| Layer | Language | Why |
|---|---|---|
| Stream processing core (Bronze/Silver) | **Java (Apache Flink)** | exactly-once, high throughput, type safety — JVM engine strengths |
| Telemetry generator / ingestion glue | **Python** | fast to write, ecosystem |
| Transform (Silver → Gold) | **SQL (dbt)** | the standard for DE transforms + data-quality tests |
| Orchestration | **Python (Airflow)** | ecosystem standard |

> Rationale is recorded in [SDD ADR-001](docs/sdd.md#adr-001-하이브리드-언어-전략-javaflink--pythonsql-글루).

## System Architecture

The core idea is **Kafka → Flink multi-sink (single-job fork)**: a single Flink job reads Kafka telemetry and streams it into ① raw preservation (Iceberg Bronze/Silver) and ② real-time serving (Elasticsearch), while ③ Gold (BigQuery) is generated separately by dbt querying Silver Iceberg via BigLake.

<details>
<summary>Text diagram (detailed)</summary>

```
[SUMO simulator (N vehicles, LuST scenario)]   (Python generator, + time acceleration → tens of millions of events)
        │  Avro binary telemetry (key = vehicle_id)
        ▼
   Apache Kafka (KRaft, self-host single-host 3-broker, RF=3/ISR=2/acks=all)
        │  at-least-once
        ▼
 Apache Flink (JobManager+TaskManager · Java · checkpoint exactly-once)  (multi-sink: Iceberg·Elasticsearch)
   │  · keyBy(event_id) dedup + state TTL, Kafka offset-aligned commit (2PC)
   │  · schema validation → bad rows to DLQ                          ▼
   │  · unbounded late data                                Elasticsearch (self-host Basic, single index, idempotent upsert)
   │  · enrich with vehicle metadata                        ├─ Kibana Maps (location/speed heatmap)
   ▼                                                        └─ Kibana Alerting (instant threshold alerts)
 ── Medallion (Lakehouse) ──
  Bronze  GCS + Apache Iceberg   (append-only raw, lossless preservation, Flink native sink)
  Silver  GCS + Apache Iceberg   (dedup / typing / outlier removal / vehicle-meta join = 1 clean row, Flink native sink)
  Gold    BigQuery               (per-vehicle avg speed/min, hard-brake count, daily fuel econ, anomaly flags, BQ ML anomaly detection)
        │  dbt (SQL, queries Silver Iceberg via BigLake) transforms + data-quality tests (store failures)
        │  Airflow scheduling & dependencies (local Airflow / GKE in-cluster during sessions, SDD §7.4/§12.7)
        ▼
  BigQuery Gold ──(BigQuery → ES template)──▶ Elasticsearch ──▶ Kibana dashboards
```

</details>

## Key Architecture

The project uses the following patterns:

- **Medallion architecture**: Bronze (raw preservation) → Silver (refined/trusted) → Gold (purpose-built aggregates), raising data quality in stages
- **Kafka → Flink multi-sink**: a single Flink job loads raw preservation (Iceberg Bronze/Silver) and real-time serving (Elasticsearch) simultaneously; Gold is generated separately by dbt via BigLake
- **Role-split hybrid languages**: Java (Flink) for the stream core, Python for glue/orchestration, SQL (dbt) for transforms — rationale in SDD ADR-001
- **Lakehouse**: Bronze/Silver are Apache Iceberg on GCS (open format, schema evolution, time travel, Flink native sink); Gold is BigQuery (dbt queries Silver Iceberg via BigLake)
- **Exactly-once processing**: Flink checkpoints (Kafka offset-aligned commit, 2PC) + Iceberg atomic commit, `keyBy(event_id)` dedup with state TTL
- **Kafka HA demo**: single-host 3-broker RF3/ISR2 — kill a broker → leader re-election → zero loss (infra HA / zone-host SPOF is out of scope)
- **Data-quality gate**: dbt tests (`unique`/`not_null`/`accepted_range`/`relationships`) store and track rule-violating rows
- **Lossless preservation**: parse-failure records are isolated in a Dead-Letter Queue (zero silent loss)
- **Separation of roles**: BigQuery = large-scale analytics/history (warehouse) + BQ ML anomaly detection; Elasticsearch = real-time search/maps (complementary)

## Tech Stack

**Ingestion & Stream Processing**

- Apache Kafka (**KRaft, self-host**, single-host 3-broker) — ingestion (RF=3 / min.insync.replicas=2 / acks=all)
- Apache Flink (**Java 21**, self-host JobManager/TaskManager) — exactly-once stream processing (Bronze/Silver, checkpoints → GCS)
- (optional) EMQX / HiveMQ — MQTT broker → Kafka

**Lakehouse & Transform**

- Google Cloud Storage + Apache Iceberg (Bronze / Silver, Flink native sink)
- BigQuery (Gold — dbt queries Silver Iceberg via BigLake)
- **dbt (SQL)** — transforms + data-quality tests
- **Airflow · Python** — orchestration (local Airflow / GKE in-cluster during sessions, SDD §7.4/§12.7)
- **BigQuery ML** (`ML.DETECT_ANOMALIES`, `ARIMA_PLUS`) — anomaly detection (on Gold)

**Serving & Analytics**

- Elasticsearch (**self-host, Basic tier**, single index, idempotent upsert by `doc_id=event_id`)
- Kibana (Maps geo visualization, dashboards, rule-based Alerting)

**Observability & Infra**

- Cloud Monitoring/Logging (default) + Prometheus·Grafana·Loki·OpenTelemetry (local development only, SDD §10.2)
- Docker, Terraform (GCP), GitHub Actions (CI)

**Data Sources**

- SUMO (TraCI) traffic simulator (**Python** generator) — fleet scale, real-time
- Kaggle Levin OBD-II driving-data replay — realism (real-world distribution calibration; comma2k19 was evaluated and rejected: see docs/sdd.md §13 R-2)

## Medallion Layers

| Layer | Content | Storage |
|---|---|---|
| **Bronze** | Raw Kafka events appended as-is — duplicates/nulls included = "evidence preservation" (schema-broken rows are losslessly isolated in the DLQ) | GCS + Iceberg |
| **Silver** | Dedup / schema validation / typing / outlier removal + vehicle-metadata join → one clean row per event | GCS + Iceberg |
| **Gold** | Purpose-built aggregates (per-vehicle avg speed/min, hard-brake count, daily fuel economy, anomaly flags) — hundreds to thousands of times smaller than raw | BigQuery (dbt) |

## Key Engineering Challenges

Problems solved (or to be solved) to handle a large stream honestly:

| Challenge | Approach |
|---|---|
| Exactly-once + deduplication | Flink checkpoints (Kafka offset-aligned commit, 2PC) + Iceberg atomic commit, `keyBy(event_id)` dedup with state TTL |
| Kafka availability (HA) | Single-host 3-broker RF3/ISR2 — kill a broker → leader re-election → zero loss (infra HA / zone-host SPOF is out of scope) |
| Late / out-of-order data | Accepted indefinitely via event-time partitioning (`ingest_time` tracks lag) — no lateness-based discard |
| Lossless preservation | Isolate parse-failure records in a Dead-Letter Queue |
| Schema evolution | Backward-compatible changes via Iceberg table format |
| Data quality | dbt tests store and track rule-violating rows |
| Local testability | Kafka·Flink·ES·Iceberg containerized E2E + BigQuery via Sandbox/DuckDB (dbt-duckdb)/bigquery-emulator |
| Load verification | Hypothesis-first load testing (set target RPS / p99 SLO, then measure & compare) |

## Project Structure

```
FleetSentinel/
├── ingestion/        # (Python) telemetry generator / SUMO & replay → Kafka
├── pipeline/         # (Java, Flink) Flink stream processing (Bronze/Silver)
├── transform/        # (SQL, dbt) Silver(Iceberg) → Gold(BigQuery), BQ ML anomaly detection, data-quality tests
├── orchestration/    # (Python, Airflow) DAGs — local Airflow / GKE in-cluster during sessions
├── serving/          # Elasticsearch mappings / Kibana dashboards & Alerting
├── schemas/          # Canonical Avro schemas (telemetry-event.avsc, dlq-envelope.avsc — SDD §6.1)
├── infra/            # Terraform (GCP), Docker, CI
└── docs/             # Architecture, schema, decision records (sdd.md, etc.)
```

## Roadmap

Implementation proceeds in five stages (ingestion → refinement → aggregation → serving → load & verification). Per-stage scope, environment, and exit criteria are documented in [SDD §16 Rollout Plan](docs/sdd.md).

## Results (to be measured)

> The figures below are filled in after real implementation and measurement. (Unverified numbers are not recorded.)

| Metric | Value |
|---|---|
| Peak throughput (RPS) | _(to be measured)_ |
| Cumulative events processed | _(to be measured)_ |
| p95 / p99 latency | _(to be measured)_ |
| Loss rate / duplicate rate | _(to be measured)_ |
| Raw-to-Gold compression ratio | _(to be measured)_ |

## Documentation

- [System Design Document (SDD)](docs/sdd.md)

## License

Distributed under the [MIT License](LICENSE).
