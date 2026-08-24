# FleetSentinel

[한국어](README.md) | [English](README-en.md)

A **data platform that ingests, monitors, and curates multimodal sensor data from autonomous vehicles and robots into machine-learning training sets.**

In one sentence:

> This is not a project that trains models. It is **a system that produces the data models are trained on.**

![Java](https://img.shields.io/badge/Java_21-ED8B00?style=flat-square&logo=openjdk&logoColor=white)
![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Apache Kafka](https://img.shields.io/badge/Apache_Kafka-231F20?style=flat-square&logo=apachekafka&logoColor=white)
![Apache Flink](https://img.shields.io/badge/Apache_Flink-E6526F?style=flat-square&logo=apacheflink&logoColor=white)
![Apache Iceberg](https://img.shields.io/badge/Apache_Iceberg-1F70C1?style=flat-square&logo=apacheiceberg&logoColor=white)
![Elasticsearch](https://img.shields.io/badge/Elasticsearch-005571?style=flat-square&logo=elasticsearch&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)

> **Status:** 🚧 **Data characterization stage** — measured what data arrives, at what scale and in what format. The ingest/ETL pipeline is not yet designed.
> **Docs (Korean):** [System Design Document](docs/sdd.md) · [Data Design](docs/data-design.md) · [Provisional pipeline notes](docs/pipeline-notes-provisional.md) · [Runbook](RUN.md)

> **Motivation (Prior Art).** A personal extension of **[AutoNotify](https://github.com/Qualcomm-Capstone)**, a Qualcomm-sponsored capstone on on-device real-time speeding detection. Feedback from a Qualcomm engineer at the final presentation — _"Catching events one vehicle at a time on the edge is solid work. But scale it to a real fleet and the bottleneck moves off the model and onto the ingest, storage, and refinement pipeline"_ — prompted generalizing single-vehicle event handling into a **fleet-scale multimodal sensor platform**. (Qualcomm was not involved in this extension.)

## The Problem

Data from a single autonomous vehicle splits into **three layers with fundamentally different
characteristics** — **signals** (CAN, IMU, steering), **perception** (3D boxes, tracks), and
**raw sensors** (6 cameras, LiDAR, 5 radars).

Two facts determine the entire architecture.

1. **Raw data is 58× heavier in bandwidth, yet signals carry 8× more messages.** Any attempt to
   push both through one pipeline collapses.
2. **One vehicle's raw output exceeds practical LTE throughput.** Not even a single vehicle can
   stream continuously.

The source data also carries limits worth stating plainly: it was collected by **2 vehicles**, and
the **longest continuous stretch is about 20 seconds**. So **"N vehicles" in this repository means
N concurrent streams**, not N distinct real vehicles.

> 📊 **Measured figures (rates, sizes, formats, per-channel detail) and source constraints live in
> [Data Design](docs/data-design.md) (Korean), which is the single source of truth.** This README
> does not restate them.

## Architecture

```
nuScenes real-world (1000 scenes × 20s)      [CARLA/OpenSCENARIO — augmentation, Phase 8]
        │
   ┌────┴─────────────────────────┐
   │                              │
① ② light  268 KB/s          ③ heavy  27 MB/s
 100ms window batching        triggered clip upload
   │ MQTT / gRPC                 │ HTTPS resumable
   ▼                              ▼
Kafka 3-broker (RF=3/ISR=2)   Object storage (MCAP segments)
   │                              │
   ▼                              │
Flink exactly-once                │
 dedup keyBy(event_id)            │
 validate → DLQ                   │
 derive ENU→WGS84                 │
   │                              │
   ├──▶ Iceberg Bronze ◀──────────┤
   ├──▶ Iceberg Silver            │
   └──▶ Elasticsearch             │
             │                    │
             ▼                    ▼
      Kibana Maps          Clip catalog (Iceberg)
      fleet monitoring    scene · time range · blob_uri · tags
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
              Rerun playback          Training-set snapshot
```

The core idea is **separating light and heavy paths (Claim-Check)**. Only references and
metadata flow through the message bus; heavy sensor payloads go straight to object storage.
The two rejoin in the clip catalog.

## Key Design Decisions

| Problem | Solution |
|---|---|
| 58× bandwidth asymmetry | **Claim-Check** — references on the bus, payloads in storage |
| Not even one vehicle can stream continuously | **Triggered clips** — onboard ring buffer, upload ±20s around events |
| Over a thousand tiny messages/sec | **Time-window batching** — 100ms provisional (transport design, see [notes](docs/pipeline-notes-provisional.md)) |
| Sensor rates span hundreds-fold | **Three timestamps** + keyframe synchronization anchor |
| Coordinates are not lat/lon | **Official-origin ENU→WGS84 conversion** |
| Raw logs must replay standalone | **MCAP with embedded calibration** |
| At-least-once ingest, zero-loss proof | **Four-stage exactly-once** + `event_id` set reconciliation |
| 23% of labels unobserved | **Quality flags as a first-class curation axis** |

Full problem-to-solution mapping is in [SDD §2–§3](docs/sdd.md) (Korean).

## Stack

**Ingest & processing** — Apache Kafka (KRaft, 3-broker RF=3/ISR=2) · Apache Flink 2.0 (Java 21, exactly-once) · MQTT / gRPC

**Storage** — Apache Iceberg (Bronze/Silver) · MinIO / GCS (MCAP originals) · **MCAP** (the robotics-standard log container)

**Serving** — Elasticsearch + Kibana Maps (fleet monitoring) · **Rerun** (multimodal sensor playback, MIT/Apache-2.0)

**Sources** — nuScenes (real-world, Boston & Singapore) · CARLA + OpenSCENARIO (scenario augmentation, stretch)

## Verification

| Gate | Result |
|---|---|
| Coordinate conversion contract (pytest) | pass |
| Lossless raw-sensor preservation | pass — 3 scenes, zero omission vs source of truth |
| **Coordinate chain, end to end** | pass — LiDAR points inside boxes vs labels, **zero error** |
| Kafka HA (hard broker kill) | pass — zero loss |
| Infrastructure smoke | pass |

Figures and methods live in [Data Design §9](docs/data-design.md). The coordinate check is the
decisive one: matching nuScenes' own labels exactly requires all five transform stages to be correct.

## Progress

| Phase | Scope | Status |
|---|---|---|
| P0 | Local infrastructure (Kafka HA, Flink, Iceberg, ES, Kibana) | ✅ |
| **P1** | **Data characterization** — scale/format measurement, coordinate system, losslessness | ✅ |
| P2 | Schema finalization · batching replayer → Kafka | next |
| P3 | Flink pipeline (dedup, validation, DLQ, sinks) | |
| P4 | Claim-Check · clip catalog | |
| P5 | Monitoring (Kibana fleet map + Rerun) | |
| P6 | Data engine (scenario mining, training-set snapshots) | |
| P7 | Protocol layer (MQTT / gRPC) | |
| P8 | CARLA augmentation (stretch) | |

## Known Limitations

Stated plainly. Full list in [SDD §4.2](docs/sdd.md).

- **Not live monitoring.** nuScenes replay reproduces bandwidth, cadence, and format, but there is no real-vehicle integration.
- **The source is 2 vehicles with a 20-second continuity ceiling.** "N vehicles" means N concurrent streams, not N distinct real vehicles.
- **Infrastructure HA is out of scope.** A single-host 3-broker setup demonstrates broker-level failover only.
- **No perception model.** Perception outputs come from nuScenes labels.
- **Radar payloads unparsed** — `.pcd` files are stored in MCAP but not decoded or visualized.

## Layout

```
FleetSentinel/
├── exploration/      # (Python) P1 data exploration — measurement/verification tools (not a pipeline)
├── flink-pipeline/   # (Java) Flink stream processing — rewritten in P3
├── infra/            # docker-compose (Kafka, Flink, Iceberg, ES, Kibana, MinIO)
├── schemas/          # canonical Avro schemas
├── scripts/          # infra smoke tests · Kafka HA demo
└── docs/             # sdd.md · data-design.md
```

## Running

```bash
make up        # start the local stack
make topics    # bootstrap Kafka topics
make smoke     # verify infrastructure
make ha-demo   # Kafka HA broker-kill demo
```

See [`exploration/README.md`](exploration/README.md) for the exploration tooling.
**That directory is not a pipeline implementation** — it holds the measurement and verification tools behind the figures in these docs.

## License

[MIT License](LICENSE). nuScenes data is subject to Motional's non-commercial terms and is not included in this repository.
