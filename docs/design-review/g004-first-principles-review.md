# G004 검토 레인 (b) — First Principles 재도출 검토

- 적용 스킬: `.claude/skills/first-principles`(환원 프로토콜·유추 경계 테스트·재도출 감사)
- 대상: `docs/sdd.md` v0.4의 스택·아키텍처 결정 전수 — 각 결정을 근본 요구로 환원해 재도출하고 `re-derived / strategy-constrained / analogy-only` 판정.
- 검토일: 2026-07-21 (야간 자율 실행)

## 1. 근본 요구(fundamentals) 명세 — 문서에서 추출·검증

| Fundamental | 값 | 출처 | 접지(ground) |
|---|---|---|---|
| 처리량 | 피크 5,000 eps (500대×1Hz×10x) | §7.1·G-2 | 산술 [verified] |
| 서빙 지연 | p99 < 300ms | G-3 | 목표치 [assumed, 명시] |
| 정합성 | 유실 0, 중복 0(경계 명시) | G-1·§6.4.1 | 설계+게이트 [verified] |
| 예산 | 월 < $300(크레딧) | §4.2·§9.1 | 실단가 fetch [verified] |
| 팀 | 1인, Java+Python 보유 | §4.2·ADR-001 | [verified] |
| **전략(비기술)** | **채용 시그널: GCP DE(메가존)·exactly-once JVM(카뱅)·거버넌스(현대차)·Elastic Stack** | ADR-001 Context | **명시적으로 명명됨** ✓ |

> 스킬의 핵심 게이트: 전략적 fundamental이 기술 필연으로 **위장**되면 blocker. → ADR-001·§12.1이 공고 요구를 Context에 명시했으므로 위장 없음. 통과.

## 2. 재도출 감사 — 결정별 판정

| 결정 | 순수 기술 재도출 결과 | 판정 |
|---|---|---|
| Pub/Sub 수집 | 5,000eps·1.6MB/s는 작은 부하 — 관리형·서버리스·retention이 1인 운영 fundamental에 최적 | ✅ re-derived |
| Dataflow/Beam(Java) 코어 | 기술만으로는 경량 컨슈머로도 가능한 규모. exactly-once·오토스케일·세션 비용($15-30) + **JVM 스트리밍 시그널(전략, 명명됨)** | ✅ strategy-constrained(정직) |
| 단일 잡 3-way 싱크 | 스트리밍 잡 상시과금이 비용 지배 → 잡 수 최소화가 예산 fundamental에서 직접 도출. R-4 커플링 리스크 명시 | ✅ re-derived |
| Iceberg Bronze | 원본 재처리(Kappa)·스키마 진화·오픈포맷 요구에서 도출. GCS raw 파일 대비 time travel·프루닝이 실질 이득. BigLake full R/W [verified] | ✅ re-derived |
| BigQuery Silver/Gold | OLAP 대량 스캔·파티션 프루닝 — 분석 fundamental 직행 | ✅ re-derived |
| ES 서빙 | "별도 프론트 없이 실시간 지도"라는 제품 fundamental → Kibana Maps(geo_point 필수)에서 역도출. + Elastic Stack 공고(전략, 명명) | ✅ re-derived + strategy |
| Avro | Pub/Sub 스키마 검증이 Avro/Proto만 지원(외부 제약=사실) + 진화 요구 | ✅ re-derived |
| dbt / Airflow 하이브리드 | 품질 게이트·의존성/백필 fundamental + 비용 floor(상시 $252 vs 세션 $10-15) 계산에서 도출 | ✅ re-derived |
| Cloud SQL/CDC = Phase 3 | 코어 fundamental에 트랜잭션 관계 데이터 없음 → 연기 결정이 재도출과 일치 | ✅ re-derived |

**analogy-only 판정: 0건.** "Netflix가 쓰니까"류 근거는 문서에 존재하지 않으며, 기각표(§12)가 각 대안을 fundamental(비용·운영·통합)로 평가함.

## 3. 비용 floor 검증 (battery treatment)
- 상시 가동 floor: Composer $252 + Dataflow 스트리밍 상시(2워커 ≈ $200+) + ES $99 ≈ **$550+/월** → 예산 위배가 **구조(상시 가동)**에서 옴을 문서가 정확히 진단하고 세션/캠페인 모델로 구조를 바꿈(§9.1·ADR-009) — 가격 fatalism 없음 ✓.
- 잔여 갭: 이벤트 크기(bytes) 가정 미명시로 Pub/Sub 비용 floor 계산이 문서 안에서 재현 불가 — cartesian 레인 m1과 동일 지적(§9.1 한 줄 필요).

## 4. 결론
- blocker 0 / major 0 / **minor 1**(m1과 공유: §9.1 이벤트 크기 가정 명시).
- 모든 결정이 `re-derived` 또는 `명명된 strategy-constrained` — 스킬 기준의 재도출 감사 통과. 유일한 상습 위반 패턴(상속된 기본값)도 G001~G003 리뷰에서 이미 제거됨(retention·TTL·임계값 전부 근거 보유).
