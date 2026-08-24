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
> **Docs (Korean):** [System Design Document](docs/sdd.md) · [Data Design](docs/data-design-v3.md) · [Provisional pipeline notes](docs/pipeline-notes-provisional.md) · [Runbook](RUN.md)

> **Motivation (Prior Art).** A personal extension of **[AutoNotify](https://github.com/Qualcomm-Capstone)**, a Qualcomm-sponsored capstone on on-device real-time speeding detection. Feedback from a Qualcomm engineer at the final presentation — _"Catching events one vehicle at a time on the edge is solid work. But scale it to a real fleet and the bottleneck moves off the model and onto the ingest, storage, and refinement pipeline"_ — prompted generalizing single-vehicle event handling into a **fleet-scale multimodal sensor platform**. (Qualcomm was not involved in this extension.)

## The Problem

Data from a single autonomous vehicle splits into **three layers with fundamentally different characteristics.**
All figures below are **measured**, not estimated (nuScenes mini, 10 scenes, 196.5 seconds, full census).

| Layer | Content | Messages/sec | Bandwidth |
|---|---|---|---|
| ① **Signals** | CAN bus, IMU, steering, ego pose | **1,295** | 432 KB/s |
| ② **Perception** | 3D object boxes, tracks, classes | 2.1 | 39 KB/s |
| ③ **Raw sensors** | 6 cameras · LiDAR · 5 radars | 159 | **27.15 MB/s** |

**Bandwidth differs by 58×, yet signals carry 8× more messages.** Any attempt to push both
through one pipeline collapses. And a single vehicle's 27.15 MB/s exceeds practical LTE
throughput (~12.5 MB/s) — **not even one vehicle can stream continuously.**

These two facts determine the entire architecture.

### Source data constraints (stated plainly)

| Item | Value |
|---|---|
| Collection vehicles | **2** (`n015`, `n008`) — this is not a fleet |
| Total driving time | 5.4 hours (1,000 scenes × 20s) |
| **Max continuous stretch** | **20 seconds** — scenes from the same vehicle on the same day sit 2–8 minutes apart and cannot be stitched |

nuScenes is not a continuous driving log; it is a **curated set of "interesting 20 seconds"
sampled from longer drives**. Precisely: *not 5.4 hours of driving, but 1,000 separate
20-second drives.*

So **"N vehicles" in these docs means N concurrent streams**, not N distinct real vehicles.
That is harmless for throughput, loss, and dedup verification (the pipeline cannot tell where
a stream came from), but the monitoring view shows vehicles teleporting every 20 seconds.
**nuPlan** (same team, multi-minute logs) is the upgrade path if continuity is needed.

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
| 1,295 tiny messages/sec | **Time-window batching** — 100ms provisional (transport design, see [notes](docs/pipeline-notes-provisional.md)) |
| Sensor rates span 937Hz–2Hz | **Three timestamps** + keyframe (2Hz) synchronization anchor |
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
| Coordinate conversion contract (pytest) | **30 passed** |
| MCAP validity | 3 scenes × 9 checks — index, embedded schemas, range random access |
| **Coordinate chain, end to end** | LiDAR points inside boxes vs labels — **31,911 points, zero error** |
| Kafka HA | Hard broker kill → leader re-election → **published 5600 = consumed 5600** |
| Infrastructure | `make smoke`, all services healthy |

The coordinate check is the decisive one: counting LiDAR points inside each 3D box and
matching nuScenes' own labels exactly requires **all five stages** —
`sensor frame → calibration → ego pose → global → box local` — to be correct.

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
└── docs/             # sdd.md · data-design-v3.md
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
