# G004 검토 레인 (a) — Cartesian Doubt 자체 검토

- 적용 스킬: `.claude/skills/cartesian-doubt`(의심 사다리·4규칙·evil-demon 패스)
- 대상: `docs/sdd.md` v0.4 핵심 주장 전수. 각 주장에 **[verified / assumed / unknown]** 라벨.
- 검토일: 2026-07-21 (야간 자율 실행)

## 1. 의심 사다리 적용 — 핵심 주장별

### 주장 1: "중복 0 (exactly-once)" (G-1, §6.4.1, §9)
- **Level 1(감각/계측)**: 설계 단계라 실측 없음 — 문서가 전부 "목표치 + §15에서 실측"으로 라벨 [verified: 문서 자기서술 정직].
- **Level 2(꿈/멘탈모델)**: "dedup이 다 막는다"는 모델은 이미 G002 리뷰에서 붕괴 → §6.4.1이 TTL 밖 잔존 경로 + 3중 방어선(stg ROW_NUMBER, source-level unique, doc_id) 문서화 [verified].
- **Level 3(악령) — 신규 발견**: 모든 dedup의 기반은 **event_id 유일성**인데, 이는 생성기 구현의 정확성에 의존하는 [assumed]다. 악령 시나리오: 생성기 버그로 **서로 다른 이벤트 2개에 같은 ULID를 부여**하면 dedup이 정상 이벤트를 **삭제**한다(중복 0 주장이 유실을 만드는 역설). ULID 충돌 확률은 무시 가능하지만 *구현 버그*(예: 재시도 루프에서 잘못된 변수 재사용)는 그렇지 않다.
  - → **[MAJOR-M1] event_id 유일성 검증 테스트가 §15에 없음.** 수정안: §14/§15에 TC-ULID-01(생성기 단위 테스트: N만 건 발급 유일성 + 재시도 시 동일 이벤트 재사용·상이 이벤트 미재사용 검증) 추가.

### 주장 2: "ES 장애 시 유실 0" (§5.4)
- 악령 패스: ES 실패 → ES DLQ(GCS) 쓰기도 실패하면? → Beam 번들 실패 → Pub/Sub 미ack 재전달(7d) — 유실 없음. GCS까지 죽으면 Bronze도 죽는 전면 장애로 리전 장애 행(NG-2)에 수렴 [verified: 문서 경로 완결].

### 주장 3: "Bronze 무손실·원본 정본" (§6.5)
- 악령 패스: Iceberg 스냅샷 커밋 재시도로 중복 append 가능 → §6.4가 "Bronze는 중복 허용이 설계 의도"로 이미 수용 [verified].

### 주장 4: "p99 < 300ms" (G-3)
- [assumed, 명시됨]: 목표치+측정방법(§15 부하시험, coordinated omission 주의 문구 존재) — 라벨 정직. 통과.

### 주장 5: "월 $170–200" (§9.1)
- 단가 = [verified] (G003 리뷰에서 공식 페이지 fetch, batch→streaming SKU 오귀속도 교정됨). 세션 20h/월 = [assumed, 명시됨]. 통과.
- **신규 발견**: 비용 계산의 기초인 **이벤트 크기(bytes) 가정이 문서에 없다**(Pub/Sub ≤1TiB/월 주장의 산출 근거 부재). → **[MINOR-m1]** §9.1에 "이벤트 ≈300B(Avro binary) × 5,000eps × 세션 20h ≈ 100GB/월 ≪ 1TiB" 한 줄 명시.

### 주장 6: "10x 시간가속" (§7.1)
- as-fast-as-possible 메커니즘 = [verified] (sumo-gui delay 문서). 그러나 **500대 LuST 시뮬이 실제 10x로 돌아간다**는 것은 하드웨어 의존 [assumed, 미명시]. 시뮬 연산이 무거우면 10x 미달 → 부하 목표(5,000eps) 미달.
  - → **[MINOR-m2]** §7.1에 "가속 배율은 시뮬 연산 성능에 의존 — LT-LOAD-01 사전 단계에서 실측 확정, 미달 시 차량 수 상향 또는 합성 생성기 병행으로 목표 eps 보정" 한 줄.

## 2. 4규칙 준수 점검
- **명증(evidence)**: 전 결정에 레퍼런스 — G001~G003 리뷰 루프에서 인용-주장 불일치 5건 검출·교정됨(#367 재프레이밍, 0.3g 재인용, step-length, Delta reader, Dataflow SKU). 현재 잔존 인용 오류 0 [verified by review receipts].
- **분석(decomposition)**: 결정이 ADR 9개 + §12.1~12.7로 분해 ✓.
- **순서(order)**: Phase 1→3 롤아웃(§16), 단순(로컬)→복잡(클라우드) ✓.
- **열거(enumeration)**: 장애 도메인 표(§5.4) 9행, DLQ 분류 3종, 적대 케이스는 QA 리포트 3본에 열거 ✓.

## 3. 결론
- blocker 0 / **major 1 (M1: event_id 유일성 테스트 부재)** / minor 2 (m1 이벤트 크기 가정, m2 가속 배율 실측 한정).
- 사다리 Level 3까지 적용해 살아남지 못한 전제는 "event_id 유일성은 공짜"라는 암묵 가정뿐 — 테스트 케이스로 명시하면 설계는 악령 패스를 통과한다.
