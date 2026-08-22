# v2.0 리뷰 통합 수정 계약 (critic 24 + architect 25 → executor 반영)

> critic REVISE(M1~M7, m1~m5) + architect REQUEST_CHANGES(major×4, minor×4). blocker 0(로컬 P1-P2 착수 가능). 아래 14개 수정을 반영해 **v2.0 확정**. 근거 URL은 fetch 검증 후 인용.

## GROUP A — docs/sdd.md (단일 소유)

**F1. sa-flink IAM ↔ dim_vehicle 로드 모순 해소** (critic M1)
- §7.2 enrich: prod에서도 `dim_vehicle`을 **GCS의 fleet CSV(생성기와 동일 소스)에서 broadcast state로 로드**(BigQuery READ 아님). 로컬/​prod 동일. dbt seed의 BQ dim_vehicle은 **Gold 조인 검증용(dbt relationships)** 으로만 분리. §5.3 sa-flink 권한에 BQ 불필요 유지(정합).

**F2. BigLake 인용 URL + 외부테이블 스냅샷 refresh** (critic M2·M4 + arch M2)
- §6.5·§7.3·§12.4의 BigLake Iceberg 인용을 **read-only 외부테이블** 정본으로 교체: `https://cloud.google.com/bigquery/docs/iceberg-external-tables`(생성) + `https://cloud.google.com/bigquery/docs/query-iceberg-data`(조회). 기존 `iceberg-tables`/`biglake-iceberg-tables-in-bigquery`(=BQ 관리형 write 제품, 설계와 상반) 제거.
- prod Iceberg 카탈로그 = **BigLake metastore(REST catalog)** 로 확정 → Flink 60s 커밋 후 BigQuery가 **자동 최신 스냅샷 조회**(수동 metadata refresh 불필요). §6.8 `uris=[…/metadata/*]` 글롭을 metastore 참조로 정정. §16.1 P1-P2 "카탈로그 2줄 교체"를 "로컬=Hadoop catalog(로컬FS/MinIO) → prod=BigLake metastore(REST), catalog-impl·warehouse·인증 명시"로 구체화(critic M4).

**F3. Airflow 클라우드 위치** (critic M3 + arch M4/W1)
- §7.4 제목 "Orchestration (Airflow / Python, 로컬 Docker Compose)" → "…**로컬(개발) / 클라우드 세션 시 GKE in-cluster**". §5.3에 세션형 접근 경로 명시: **세션 동안 Airflow도 GKE in-cluster 기동**(Kafka/Flink/ES 동일 노드군, §12.7 self-host 통일 논지) — 로컬 개발 시 Flink REST/ES 접근은 `kubectl port-forward`. §16.1 P5/P6에 오케스트레이터 위치(in-cluster) 반영.

**F4. TC-RECON-01 대사 항등식 정의** (critic M5)
- §15/§14: 명시 항등식 — `distinct_published = Silver_COUNT(DISTINCT event_id) + telemetry.dlq_distinct(검증실패 3종만)`. **SINK_WRITE_FAILURE는 대사에서 제외**(이미 정본 도달, 더하면 이중계산). 생성기 "발행 카운터 = distinct event_id 기준"(attempt 아님) 명시. Bronze는 raw count가 아니라 별도 "중복 관측" 지표로 분리.

**F5. G-4/이상탐지 스트레치 게이팅 + tripwire severity** (critic M6)
- §14 Traceability + §16.1: G-4(dbt 품질게이트)·이상탐지(BQ ML)는 **스트레치(P5) 게이트**임을 표기(MVP 충족 목표집합과 구분). §7.3 source-level `unique(event_id)` 테스트 **severity=warn**으로 고정. §9 NFR/§6.4.1 문구를 "**stg ROW_NUMBER dedup=차단(block) + dbt unique=탐지(tripwire, warn)**"로 분리 → G-4 "store_failures 0행"이 tripwire 발동과 설계상 모순되지 않게.

**F6. 버전 매트릭스** (critic M7)
- §4.1 하단(또는 부록)에 고정 버전 표: Flink(예 1.20.x)·Iceberg(예 1.6.x)·Kafka 이미지(apache/kafka 3.9.x, KRaft)·Elasticsearch(8.x)·flink-connector-iceberg·flink-connector-elasticsearch·state backend(RocksDB). 로컬(§16.1)/prod 동일 버전 사용 명시. **정확 버전은 호환 매트릭스 fetch 확인 후** 기입(Flink-Iceberg-ES 호환 윈도우).

**F7. Iceberg 유지보수 DAG** (arch m1/W4)
- §7.4에 5번째 DAG **`iceberg_maintenance`**(일 1회): `rewrite_data_files`(compaction) + `expire_snapshots`(7~30일 보존) + `remove_orphan_files`. 근거: `https://iceberg.apache.org/docs/latest/maintenance/`·`/flink-maintenance/`(fetch 검증). §6.3 Silver "삭제 없음"을 "**데이터 보존, 오래된 스냅샷/고아 파일은 iceberg_maintenance가 정리**"로 정정.

**F8. Iceberg upsert ↔ 잔존 중복 근거** (critic m2)
- §6.4.1 또는 §6.8에 1줄: "Iceberg `write.upsert.enabled`는 **파티션 스코프 equality delete**라 event_time 파티션이 다른 late 재전달은 제거 못 함 → stg ROW_NUMBER dedup이 belt-and-suspenders."

**F9. §7.4 DAG 표 MVP/스트레치 열** (critic m4)
- DAG 표에 MVP/스트레치 열: `backfill_manual`=MVP(리플레이), `dbt_hourly`·`bq_to_es_daily`·`es_retention_daily`·`iceberg_maintenance`=Gold/서빙 의존이라 스트레치(단 iceberg_maintenance는 Silver 의존이라 MVP 후반).

**F10. Kafka 스키마 핀 고정 1줄** (critic m5)
- §8.1: "Schema Registry 미사용 → producer/consumer가 동일 `.avsc` 핀 고정(리더 관리), 온-와이어 스키마 진화는 수동(동결 스키마라 MVP 무영향)."

**F11. §13 Owner {이름} 허용 위치 정합** (arch m4)
- §3 서두(또는 §0 안내문) "{이름} 허용 위치" 열거에 "**리스크 Owner 칸**" 추가(자기모순 해소).

**F12. ADR 번호 재사용 정합** (arch m2/W2 + critic 연계)
- §11 서두에 주석 추가: "**v2.0은 ADR 전면 re-baseline**(v1.0 대비 아키텍처 전환). ADR-002/003/005/006/007/009는 v1.0과 동일 번호이나 결정 내용이 갱신·대체됨 — v1.0 원문은 git 히스토리 참조." + 매핑 요지(v1.0 ADR-009 오케스트레이션 → v2.0 §7.4/§12.7 강등). 모든 내부/외부(README) 참조가 이 매핑과 일치하도록.

**F13. 텍스트 다이어그램 정본 명시** (arch m3)
- §5.2 PNG 경고문 유지 + "**아래 텍스트 다이어그램이 v2.0 정본**" 상단 강조(PNG 재생성은 P1 전 백로그).

## GROUP B — schemas/*.avsc (doc만) + README 2본

**F14a. avsc doc 문자열 v2.0 갱신** (critic m1 + arch M1) — **필드·타입·이름 절대 변경 금지, doc 주석만**:
- `telemetry-event.avsc`: record doc "Silver(BigQuery)"→"Silver(Iceberg)", "Pub/Sub 스키마 검증"→"Kafka topic + 클라이언트측 Avro 검증(§8.1)". event_id doc "Dataflow exactly-once/Beam Deduplicate/BigQuery Storage Write API 오프셋"→"Flink keyBy(event_id) 상태 dedup / Iceberg 2PC 커밋 / ES doc_id 멱등". event_time doc "BigQuery event_time 파티션"→"Iceberg days(event_time) 파티션".
- `dlq-envelope.avsc`: error_class doc의 "BQ→GCS dlq/bq/" 제거(§6.7이 소멸 명시), SINK_WRITE_FAILURE 예시를 Iceberg/ES write 실패로. source_subscription doc "Pub/Sub subscription"→"Kafka 소스 식별자(consumer group/topic)". pipeline_step 예시 "sink-bq"→"sink-iceberg/sink-es".

**F14b. README 2본 정합** (arch M3 + m3):
- L68·L104·L152(KO/EN): **Cloud Composer/Composer 세션 제거** → 로컬 Airflow / 세션 시 GKE in-cluster. "SDD ADR-009" → "**SDD §7.4/§12.7**".
- L39(KO/EN): ADR-001 앵커를 `#adr-001-하이브리드-언어-전략-javaflink--pythonsql-글루`로 정정(v2.0 제목 슬러그).

## 검증(수정 후)
- 마커 스캔 잔존 = {이름}만. Pub/Sub·Dataflow·Elastic ML·Composer·dlq/bq/ 라이브 서술 0(기각/역사 맥락만).
- 신규 인용 URL(iceberg-external-tables·query-iceberg-data·iceberg maintenance·버전 호환) fetch 검증.
- ADR 앵커(내부+README) 전수 유효.
