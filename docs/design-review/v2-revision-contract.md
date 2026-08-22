# FleetSentinel SDD v2.0 개정 계약 (리더 확정 — executor는 이대로 반영)

> 전환: v1.0(**Pub/Sub + Dataflow 관리형**) → v2.0(**자체호스팅 OSS 스트리밍 레이크하우스: Kafka + Flink + Iceberg + ES**). 사용자 결정 반영. 스코프는 단계 분리로 2주 방어.

## A. 확정 결정 (전부 SDD에 반영)

1. **수집 = Apache Kafka**(코어, Pub/Sub 대체). self-host. **KRaft(ZooKeeper 없음)**, 공식 `apache/kafka` 이미지, **Strimzi 미사용**. HA "흉내": **단일 호스트에 브로커 3개**(GKE StatefulSet `replicas:3` 권장 — ecommerce 패턴에서 1→3; 로컬=docker-compose 3컨테이너). **RF=3 / min.insync.replicas=2 / acks=all / unclean.leader.election=false**, offsets·txn state RF=3. 데모 = **브로커 1개 kill → 리더 재선출 → 유실 0 · 계속 처리**. 정직 프레이밍: "broker-level 복제·failover 시연, 인프라 HA(존/호스트 SPOF)는 스코프 밖". Pub/Sub은 §12에 "GCP 관리형 대안으로 검토했으나 자체운영 스트리밍 시그널 위해 Kafka 채택"으로 기각 근거만.

2. **처리 = 네이티브 Apache Flink**(코어, Dataflow/Beam 완전 제거). self-host(**JobManager + TaskManager**, RocksDB state backend, **체크포인트 → GCS**). API = DataStream + Flink SQL. **exactly-once = Kafka 소스 오프셋 + 체크포인트 정렬 커밋(2PC 싱크)**. **dedup = `keyBy(event_id)` + 상태 TTL**(v1.0의 Beam Deduplicate 대체). 집계용 이벤트타임 윈도우는 코어에 없음(정제·라우팅만) — v1.0과 동일.

3. **저장 = Iceberg 중심**. **Bronze + Silver = Apache Iceberg**(Flink 네이티브 Iceberg 싱크, GCS). **Gold = BigQuery**(dbt가 **BigLake 외부테이블로 Silver Iceberg를 조회**해 Gold 생성). Iceberg가 오픈포맷 backbone, BigQuery는 최종 분석/ML 층. v1.0의 "Silver=BigQuery"는 **"Silver=Iceberg"로 변경**.

4. **서빙 = Elasticsearch self-host**(Docker/GKE, 무료 **Basic tier**). **Flink Elasticsearch 커넥터**로 실시간 색인(`doc_id=event_id` 멱등 upsert). Kibana Maps(geo_point) = 제품 시각화. 단일 인덱스 + delete-by-query 보존(v1.0 유지). Elastic Cloud는 self-host 기본, elastic.co 직접가입 14일 trial은 곁들이기 옵션(GCP Marketplace 경유는 trial 미적용 — hosting-and-ml-decisions.md).

5. **이상탐지 = BigQuery ML**(`ML.DETECT_ANOMALIES`, 시계열 `ARIMA_PLUS`, Gold 대상) + Kibana 규칙 알림(Basic). **Elastic ML 드롭**(Platinum 유료라 self-host Basic 미포함). → ADR-010.

6. **오케스트레이션 = Airflow**(로컬 Docker Compose / 세션형) — dbt·BQ ML·ES 보존 스케줄. (Flink 잡 제출도 Airflow가 트리거 가능.)

7. **인프라·비용 = 자체호스팅**. Kafka+Flink+ES = **GKE(권장) 또는 GCE self-host** → **크레딧 커버(1st-party 컴퓨트)**. 비용 단위 = **GKE/GCE node-hours**(관리형 세션비 모델 대체). $300 크레딧·2주 내: 소형 GKE(노드 2~3)면 여유. 상시 가동 시 압박 → **캠페인 stop/start**. BigQuery/GCS는 관리형 그대로(소액). §9.1 비용표 전면 재산정.

8. **로컬 테스트성(§15 강화)**: Kafka·Flink·ES·Iceberg 전부 컨테이너라 **Kafka→Flink→Iceberg→ES 전 구간 로컬 E2E 가능**(로컬 Iceberg 카탈로그 Hadoop/REST + MinIO, DuckDB/pyiceberg 검증). **BigQuery만 로컬 대체 없음**: (a) dbt/SQL 로직 = **DuckDB(dbt-duckdb)/dbt unit test**, (b) DDL/쿼리 = **`goccy/bigquery-emulator`**(Docker+Testcontainers, 부분 커버), (c) GEOGRAPHY·BQ ML·BigLake = **BigQuery Sandbox**(무료·카드 불필요). Iceberg 중심이라 BQ 의존이 Gold 층으로 축소된 게 v1.0 대비 개선점 — 명시. → ADR-011.

9. **스코프 단계(§13 리스크 + §16 롤아웃)**: **MVP(2주 핵심)** = Kafka HA(브로커kill 데모) + Flink exactly-once + Iceberg(Bronze/Silver) + Kibana 지도 = 돌아가는 end-to-end. **스트레치** = BQ ML, Gold 집계(우선 2~3개), CDC. 스트레치 미완료여도 데모 성립. R-신설: "3개 self-host 클러스터 운영 복잡도 → MVP/스트레치 분리로 완화".

## B. 유지 (v1.0 그대로, 변경 금지)
- `schemas/telemetry-event.avsc`·`dlq-envelope.avsc` — Kafka Avro 페이로드. **event_time = 발행 시점 wall-clock UTC**. DLQ 4분류(SINK_WRITE_FAILURE 포함).
- Medallion, polyglot 정본/사본, GIS(geo_point/GEOGRAPHY/convertGeo/lat-lon 순서), event_id 발급 계약(생성기 1회·재시도 불변), TC-DEDUP-01/DLQ-01/ULID-01/RECON-01/LT-LOAD-01, §15 LT 프로토콜(open-model·CO 회피·대사), G-1~G-5.
- **미결정 0 원칙**(허용 예외 `{이름}`만), 모든 결정에 근거+레퍼런스(URL은 web_search로 실재 검증 후 인용), effectively exactly-once 용어.

## C. ADR 재편 (§11)
- ADR-001 하이브리드 언어: **Java(Flink)** + Python(Airflow·생성기) + SQL(dbt·Flink SQL)로 갱신.
- ADR-002: **수집=Kafka(self-host KRaft 3-broker)** 코어, Pub/Sub 기각 근거.
- ADR-003: **Bronze+Silver=Iceberg(Flink 싱크)**, Gold=BigQuery(BigLake). Delta/Hudi/BQ-native 기각 유지.
- ADR-004: polyglot 정본/사본(ES=재구성 사본) — 유지.
- ADR-005: **처리=네이티브 Flink**(vs Dataflow/Spark) — v1.0 Kappa/ADR 뒤집기(Dataflow 기각).
- ADR-006: **Flink exactly-once**(Kafka 오프셋+체크포인트 2PC + Iceberg 원자 커밋) + ES doc_id 멱등.
- ADR-007: **인프라=GKE/GCE 자체호스팅**(vs 관리형), 크레딧·비용 근거.
- ADR-008: Avro 유지(Kafka는 Schema Registry 옵션 — Confluent SR self-host or 스키마 파일 관리; 간단히 스키마 파일 + 클라이언트 검증).
- ADR-009: **Kafka HA 범위**(단일호스트 3브로커 RF3/ISR2, 브로커장애 흉내, 인프라HA 스코프밖).
- ADR-010: **이상탐지=BQ ML**(Elastic ML 드롭).
- ADR-011: **로컬 테스트 전략**(Iceberg 중심 로컬 E2E + BQ Sandbox/DuckDB/emulator 3층).

## D. 섹션별 변경 요약
- §0 메타: Version **2.0**, Status Draft(재검토 예정), 리비전 2.0 행(전환 요지). Related에 hosting-and-ml-decisions.md 링크.
- §1 소개: 스코프에 "자체호스팅 OSS 스트리밍" 반영.
- §2 개요: 다이어그램·서사 = Kafka→Flink→Iceberg(+BQ/ES). "하나의 스트림 3-way 싱크"는 Flink 다중 싱크로 재서술.
- §4.1 스택표: Pub/Sub→Kafka, Dataflow→Flink, Silver BQ→Iceberg, 관측성·인프라 갱신. 언어 요약 갱신.
- §5 아키텍처: 5.1 스타일(자체호스팅 스트리밍 레이크하우스), 5.2 컴포넌트(Kafka/Flink/Iceberg/BQ/ES 책임·인터페이스), 5.3 배포(GKE 토폴로지·Flink 클러스터·Kafka 3브로커·체크포인트 GCS·IAM), 5.4 장애도메인(브로커kill·Flink 체크포인트 복구·TaskManager 장애 등).
- §6.4.1 처리 의미론: **Flink 체크포인트 exactly-once + keyBy dedup**로 재작성. §6.5 저장전략(Iceberg 중심). §6.8 Bronze/Silver=Iceberg DDL(Flink), Gold=BQ DDL(dbt via BigLake).
- §7: 7.1 생성기(Python→Kafka), 7.2 **Flink Stream Processor**(DataStream/SQL, 체크포인트, 3싱크), 7.3 dbt(BigLake로 Silver Iceberg 읽어 Gold), 7.4 Airflow, 7.5 ES 서빙.
- §8 인터페이스: Kafka 토픽(Avro), Iceberg/BQ/ES 계약.
- §9.1 비용: GKE/GCE node-hours 재산정(Kafka+Flink+ES 노드), BQ/GCS 소액, 상한 시나리오, 크레딧 내.
- §12 대안: 스트림엔진(Flink 채택 vs Dataflow/Spark 기각), 수집(Kafka vs Pub/Sub), 저장(Iceberg) 갱신.
- §13 리스크: 3-클러스터 운영 복잡도 + MVP/스트레치 완화.
- §15 테스트: 위 §A.8 로컬 테스트 3층 명시.
- §16 롤아웃: MVP/스트레치 단계 + P1-P2 로컬 스펙(Flink 로컬·Iceberg 로컬·Kafka compose).
- §18 Open Questions 0 유지.

## 검증
- 신규 인용 URL(Flink Iceberg 싱크, Flink exactly-once/checkpointing, Kafka KRaft, BigLake Iceberg, goccy bigquery-emulator, dbt-duckdb, BQ Sandbox)은 web_search/read로 실재 검증 후 인용.
- 미결정 마커 스캔 잔존 = `{이름}`만.
