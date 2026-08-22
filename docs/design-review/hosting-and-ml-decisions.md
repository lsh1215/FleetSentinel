# 호스팅·이상탐지 결정 리서치 (2026-07-22)

> 배경: GCP $300 무료 크레딧이 **3rd-party Marketplace(Confluent Cloud·Elastic Cloud via Marketplace)에 적용 안 됨**(무료 체험 계정은 Marketplace 사용 자체가 차단, [GCP 공식](https://docs.cloud.google.com/free/docs/free-cloud-features)). 그래서 ES·Kafka는 **컨테이너 self-host**(GKE/Docker = 1st-party 컴퓨트라 크레딧 커버)를 기본으로 한다. 본 문서는 그 전제하의 세부 결정.

---

## 1. Elastic Cloud 14일 무료 trial — 한계 (self-host가 기본, 혹시 쓸 경우 대비)

출처: [Elastic Pricing FAQ](https://www.elastic.co/pricing/faq) · [Evaluate Elastic during a trial](https://www.elastic.co/docs/get-started/evaluate-elastic) · [Cloud trial overview](https://www.elastic.co/cloud/cloud-trial-overview) · [Sign up & org](https://www.elastic.co/docs/deploy-manage/deploy/elastic-cloud/create-an-organization)

| 항목 | 내용 |
|---|---|
| 기간 | **클러스터 생성 순간부터 14일**, 신용카드 불필요 |
| 기본 제공 | hosted deployment 1개(8GB RAM/240GB) + Serverless project 3개 |
| 크기 제한 | 데이터노드 **AZ당 4GB RAM, 최대 2 AZ(총 8GB)**, **동시 배포 1개만** |
| 기능 제한 | **ML/LLM 토큰 사용 제한**, Serverless는 Search Power 100·Boost Window 7일·스케일링 제한 |
| 만료 시 | 배포 **suspend** → **30일 내 미구독 시 배포·데이터 영구 삭제**. 구독하면 재개·데이터 복구 |
| 결제 | trial 이후 계속 쓰려면 신용카드 필요(사용량 과금) |
| ⚠️ **GCP 경유 함정** | **"signing up through Microsoft Azure and Google Cloud does not come with a free trial"** — GCP Marketplace로 가입하면 **14일 trial 미적용**. trial 쓰려면 **elastic.co 직접 가입** 필수 |

**판단**: trial은 14일·8GB·기능제한이라 "잠깐 써보기"엔 충분하나 **포트폴리오 상시 가동엔 부적합**. 기본은 self-host, Elastic Cloud는 elastic.co 직접가입 trial로 **곁들이기만** 가능.

---

## 2. 이상탐지: BigQuery ML vs Elastic ML → **BigQuery ML 채택** (ADR-010 후보)

| 기준 | Elastic ML | **BigQuery ML** ✅ |
|---|---|---|
| self-host 비용 | **Platinum 유료** — 무료 Basic tier 미포함 | BQ에 포함, 크레딧 커버, **영구** |
| 데이터 위치 | ES로 이동 필요 | **이미 Gold(정본)에 존재** — 이동 0 |
| 실행 위치 | ES 클러스터 | BigQuery(Gold) — 스택에 이미 있음 |
| DE 채용 시그널 | "관리형 ML 토글" | **"SQL-native ML을 dbt Gold에 통합"** = 더 강함 |
| 지속성 | 30일 trial 후 유료 | 영구 |

**결정**: 이상탐지 학습 모델은 **BigQuery ML** (`ML.DETECT_ANOMALIES`, 시계열은 `ARIMA_PLUS`).
- **근거(제1원리)**: self-host 기본 = Basic tier = Elastic ML 애초에 사용 불가 → self-host 방침과 충돌. 이상탐지 대상 데이터(급가속·과열·연비 패턴)의 정본이 이미 BigQuery Gold라, 데이터를 옮기지 않고 그 자리에서 SQL로 학습·탐지하는 게 자연스럽고 크레딧으로 영구 유지된다.

**역할 분담(3층)**:
1. **규칙 기반 임계** = Gold 집계(`accel>3.0`, `coolant>105` 등 §6.8) — 결정론적, ML 아님.
2. **학습 기반 이상탐지** = **BQ ML**(배치, Gold) — 차량별 패턴 이탈 등.
3. **실시간 임계 알림** = **Kibana Alerting**(Basic 무료) — 규칙 기반 실시간 경보.
- **Elastic ML = 드롭**(원하면 elastic.co 직접가입 30일 trial로 데모만).

→ SDD 반영 시 **§7.5·§4.1·§9.1의 "Elastic ML" 제거/강등 + ADR-010(이상탐지=BQ ML) 신설**.

---

## 3. Kafka self-host 패턴 — ecommerce-microservices 선례 재활용 (Strimzi 불필요)

확인 결과: `~/My_Project/ecommerce-microservices`는 **오퍼레이터(Strimzi/Confluent) 미사용**. 손수 짠 경량 배포:

| 환경 | 파일 | 방식 |
|---|---|---|
| k8s | `k8s/base/kafka-statefulset.yml` | 순수 `StatefulSet`, `image: apache/kafka:3.8.1`(공식), **KRaft**(ZK 없음, `KAFKA_PROCESS_ROLES: broker,controller`), **단일 브로커**(`replicas:1`), RF=1, 전용 노드(`nodeSelector: role: kafka`), 헤드리스 서비스 + 2Gi PVC. 주석: *"cost-aware evidence runs"* |
| 로컬 | `infra/docker-compose.yml` | 같은 `apache/kafka:3.8.1` 단일 컨테이너, KRaft |

**판단**: FleetSentinel이 Kafka 트랙을 갈 경우 **이 단일 브로커 StatefulSet/compose 패턴을 그대로 재활용**하면 됨 — Strimzi 셋업 시간 부담 없음, Redpanda 대체도 불필요. 검증된 자기 자산 재사용이 2주 스프린트에 최적.

- 참고: Dataflow가 Kafka를 읽는 건 Beam **KafkaIO** — 처리 계층 코드는 거의 안 바뀜(수집 인터페이스만 교체).

---

## 후속(SDD 반영 대기 — 사용자 방향 확정 후 일괄)
- §5.3 ES 호스팅: Elastic Cloud → **self-host(Docker 로컬 / GKE StatefulSet)**, Elastic Cloud는 trial 곁들이기 옵션.
- §9.1 비용표: $99 Elastic 제거 → GKE node-hours 재산정.
- §7.5·§4.1: Elastic ML → **BQ ML**(ADR-010).
- ADR-002: Pub/Sub 기본 + **self-host Kafka(단일 브로커 StatefulSet) 대체 경로** 명시(pluggable ingestion).

---

## 4. Kafka HA 범위 — 브로커 장애 "흉내"(존/호스트 HA 아님)

사용자 확정 스코프: 장애 단위 = **broker 프로세스(pod/컨테이너) 죽음**, 호스트/존 장애 아님. → **머신 1대**로 충분. 존 분산·3 VM·rack awareness·MIG는 **드롭**(오버스코프).

- **토폴로지**: 1 머신에 **브로커 3개**(GKE면 StatefulSet `replicas: 3` — ecommerce 패턴에서 1→3만; GCE VM이면 docker-compose 브로커 3 컨테이너). "pod 죽는 상황" 관점이면 **GKE가 더 자연스러움**.
- **HA를 실제로 만드는 복제 설정(핵심)**: `replication.factor=3`, `min.insync.replicas=2`, `acks=all`, `offsets.topic.replication.factor=3`, `transaction.state.log.replication.factor=3`/`min.isr=2` → 브로커 1개 kill 시 리더 재선출·유실 0·계속 가용.
- **데모**: 브로커 하나 `kill` → 클러스터 생존 시연(복제·ISR·리더선출).
- **정직한 프레이밍(필수)**: README/면접에서 "단일 호스트 3브로커로 **broker-level 복제·failover 시연(RF=3/ISR=2)**, 인프라 HA(존/호스트 SPOF)는 스코프 밖"으로 명시. "3브로커=HA"로 뭉개지 않는다.
- **KRaft/Strimzi/ZK**: KRaft(ZK 없음), **Strimzi 미사용**(단일 호스트 3브로커엔 오퍼레이터 불필요).

**미결(사용자 결정 대기)**: Kafka = 코어 수집(Pub/Sub 대체) vs 대체 트랙. HA가 1머신으로 경량화돼 대체 트랙 부담도 낮아짐. 결정 후 SDD(ADR-002 개정 + Kafka ADR) 반영.
