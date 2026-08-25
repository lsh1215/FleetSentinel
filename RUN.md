# FleetSentinel — 로컬 인프라 실행 절차

> **상태 (v3.0 전환 중).** 자율주행 멀티모달 도메인으로 전환하면서 v2.0 파이프라인
> (합성 생성기 · Flink 잡 · OBD 서빙 계층)은 제거했다. 현재 이 문서가 다루는 범위는
> **도메인 무관 인프라 계층**뿐이다.
> 데이터 설계는 [`docs/data-design.md`](docs/data-design.md), 전체 설계 이력은
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
| jobmanager / taskmanager | 8081 | Flink 2.0 클러스터 (잡 미배포 상태) |
| minio | 9000 / 9001 | S3 호환 오브젝트 스토리지 (GCS 로컬 대체) |
| iceberg-rest | 8181 | Iceberg REST 카탈로그 |
| clickhouse | **8124**(HTTP) / 9009(네이티브) | 신호·인지 시계열, 클립 카탈로그 |

## 2. 토픽 부트스트랩

```bash
make topics
```

RF=3 / `min.insync.replicas=2`로 생성한다. 토픽 이름은 v3.0 스키마 확정 시 재정의 대상이다.

## 3. 스모크 테스트

```bash
make smoke
```

전 서비스 healthy · 토픽 존재 · **ClickHouse 질의·지리 함수** · MinIO 버킷 · Iceberg REST를 단언한다.

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

## 다음 단계 (v3.0 재작성 대기)

[`docs/data-design.md`](docs/data-design.md) §6 기준으로 아래를 새로 만든다.

1. 스키마 3종 필드 계약 확정 (`vehicle-signal` / `perception-object` / `log-segment`)
2. 100ms 배치 재생기 → Kafka
3. Flink 파이프라인 (dedup · 검증 · DLQ) → **ClickHouse** 적재
4. Claim-Check 경로 (MCAP 세그먼트 → 오브젝트 스토리지)
5. Spring Boot 4 API + React 대시보드
