# FleetSentinel — 로컬 인프라 실행 절차

> **상태.** 이 문서는 **로컬 인프라 계층**만 다룬다. Kafka→Flink→ClickHouse 파이프라인은
> 아직 구현하지 않았으므로(P2·P3) 기동해도 데이터가 흐르지 않는다.
>
> 실행할 수 있는 다른 두 갈래는 아래에 있다 — **차량 측 구현 테스트**(§6)와
> **대시보드**(§7). 둘은 인프라 스택과 독립적으로 돈다.
>
> 데이터 설계는 [`docs/data-design.md`](docs/data-design.md), 전체 설계는
> [`docs/sdd.md`](docs/sdd.md)를 참고한다.

## 0. 사전 준비

- Docker Desktop (메모리 6GB 이상 권장 — Kafka 3 + Flink 2 + ClickHouse + MinIO)
- `make`, `bash`

## 1. 스택 기동

```bash
make up      # 전 서비스 healthy까지 대기
make ps      # 상태 확인
```

기동되는 서비스:

| 서비스 | 포트 | 용도 |
|---|---|---|
| kafka1 / kafka2 / kafka3 | 29092 (호스트) | KRaft 3-broker, RF=3 / min.insync.replicas=2 |
| jobmanager / taskmanager | 8081 | Flink 클러스터 (잡 미배포 — P3) |
| minio | 9000 / 9001 | S3 호환 오브젝트 스토리지 (GCS 로컬 대체) |
| iceberg-rest | 8181 | Iceberg REST 카탈로그 |
| clickhouse | **8124**(HTTP) / 9009(네이티브) | 신호·인지 시계열, 클립 카탈로그 |

## 2. 토픽 부트스트랩

```bash
make topics
```

RF=3 / `min.insync.replicas=2`로 생성한다. 토픽 이름은 P2 스키마 확정 시 재정의 대상이다.

## 3. 스모크 테스트

```bash
make smoke
```

전 서비스 healthy · 토픽 존재 · **ClickHouse 질의·지리 함수** · MinIO 버킷 · Iceberg REST를 단언한다.

> Iceberg REST 카탈로그는 **현재 설계에서 쓰지 않는다**(테이블 포맷 보류 —
> [SDD §1.5](docs/sdd.md)). P6에서 학습셋 버저닝이 필요해질 때를 위해 남겨둔 것이고,
> 스모크는 컨테이너가 살아 있는지만 확인한다.

## 4. Kafka HA broker-kill 데모

```bash
make ha-demo
```

전용 토픽(`ha-demo`)에 `kafka-producer-perf-test`로 발행하는 도중 브로커 1대를 **하드 kill(SIGKILL)**
하고, 리더 재선출 → ISR 복원 → **유실 0**(consumed ≥ published)을 오프셋으로 대사한다.

- 외부 의존이 없다 — 부하 발생기는 Kafka 이미지 내장 도구를 쓴다.
- `VICTIM=kafka3 make ha-demo` 처럼 대상 브로커를 바꿀 수 있다.
- **정직한 한계(ADR-009)**: 단일 호스트 3-broker이므로 broker-level 복제·failover만 실증한다.
  호스트·존 SPOF는 스코프 밖이다.

## 5. 종료

```bash
make down     # 볼륨 유지
make clean    # 볼륨·데이터까지 삭제
```

## 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `make up`이 healthy 대기에서 멈춤 | Docker 메모리 부족. Desktop 설정에서 8GB 이상 할당 |
| ClickHouse HTTP 응답이 이상함 | **호스트 8123을 다른 프로세스가 점유**할 수 있어 8124로 매핑했다. `lsof -nP -iTCP:8124 -sTCP:LISTEN`으로 확인 |
| Flink TaskManager exit 137 | OOM. Docker 메모리 상향 후 `make restart` |
| `ha-demo` 중 ISR 미복원 | 브로커 재기동이 느린 경우. `make ps`로 상태 확인 후 재실행 |

## 6. 차량 측 구현 테스트 (인프라 불필요)

온보드 유실 방지 경로 — WAL · 누적 ack · `seq` dedup. 도커 스택 없이 돈다.

```bash
cd exploration
./setup-venv.sh                                    # 최초 1회 (nuScenes devkit numpy 충돌 회피 2단계)
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q  # 82건
```

SIGKILL 테스트가 자식 프로세스를 강제 종료하므로 몇 초 걸린다. 설계는
[`docs/wal-design.md`](docs/wal-design.md) · [`docs/ack-dedup-design.md`](docs/ack-dedup-design.md).

## 7. 대시보드 (인프라 불필요)

```bash
cd frontend
npm install
npm run dev        # Vite + 목업 SSE 스트림
```

**목업 스트림은 난수가 아니다** — 실 nuScenes에서 뽑은 픽스처를 설계상 전송 단위로 재생한다.
픽스처는 라이선스상 커밋하지 않으므로 없으면 생성해야 한다
([`frontend/README.md`](frontend/README.md)).

## 다음 단계 — 클라우드 파이프라인

[`docs/data-design.md`](docs/data-design.md) §4 필드 계약 기준으로 아래를 새로 만든다.

1. 스키마 3종 확정 (`vehicle-signal` / `perception-object` / `segment-ref`) — `event_id`를 빼고 `(vehicle_id, boot_id, seq)`로
2. **레코드 단위** 재생기 → Kafka (배치는 [뒤집혔다](docs/ingestion-design-review.md) §4.1)
3. Flink 파이프라인 (`seq` dedup · 검증 · DLQ) → **ClickHouse** 적재
4. Claim-Check 경로 (MCAP 세그먼트 → 오브젝트 스토리지)
5. Spring Boot 4 API → 대시보드를 목업에서 실 API로 전환
