# G004 통합 발견 대장 (5레인 → 수정 추적)

- 레인: (a) cartesian-doubt(리더) · (b) first-principles(리더) · (c) critic(agent 16) · (d) architect(agent 17) · (e) gemini CLI 외부 리뷰
- 상태: `open → fixed → re-verified`

| ID | 레인 | 심각도 | 위치 | 내용 | 수정 방침 | 상태 |
|---|---|---|---|---|---|---|
| G1 | gemini | **BLOCKER** | §5.4·§5.2·ADR-006 | BQ 지속 실패 시 "배치 재적재 전환" 메커니즘 부재(트리거·경로·누락분 처리 미정의) | BQ 실패 사이드 출력 → GCS `dlq/bq/`(비동기 백필 패턴: 배치 잡이 재적재) 명시 + 싱크 분리 대안 비교를 ADR-006 Consequences에 기록 | **fixed** |
| G2 | gemini | MAJOR | §9.1 | Dataflow Streaming Engine 데이터 처리 과금 수치 누락(과소평가 위험) | 이벤트 크기 가정(~300B Avro)과 함께 SE 처리량(세션 20h ≈ ~110GB, ~$2)·셔플/상태 오버헤드 감안 상한을 수치로 명시, 합계 재확인 | **fixed** |
| G3 | gemini | MAJOR | §10 | CI/CD 파이프라인·모니터링 대시보드 구체성 부재 | §10.5 CI/CD 신설(GitHub Actions 단계: 테스트→빌드→Flex 템플릿/이미지→Terraform plan) + §10.2에 핵심 메트릭 목록(백로그·워터마크 지연·DLQ 카운트·ES p99) | **fixed** |
| M1 | cartesian | MAJOR | §14·§15 | event_id 유일성이 [assumed]인데 검증 테스트 부재(버그 시 dedup이 정상 이벤트 삭제) | TC-ULID-01 신설(§14 행 + §15 Unit에 명시) | **fixed** |
| G4 | gemini | MINOR | G-1·§9 | "exactly-once" 용어가 잔존 한계 대비 과강 | "effectively exactly-once(경계 명시)" 용어로 정밀화 | **fixed** |
| G5 | gemini | MINOR | §18B | 0.2s 인플라이트 가정 근거 없음 | "초기 가설 — 소규모 부하로 실측 보정(LT-LOAD-01 사전 단계)" 명시 | **fixed** |
| G6 | gemini | MINOR | ADR-009 | 로컬/Composer 메타DB 비공유 미명시 | Consequences에 "상태 비공유, Composer 세션은 독립 실행 환경" 추가 | **fixed** |
| m1 | cartesian+FP | MINOR | §9.1 | 이벤트 크기(bytes) 가정 미명시 → 비용 floor 재현 불가 | G2와 함께 해결 | **fixed** |
| m2 | cartesian | MINOR | §7.1 | 10x 가속 배율이 하드웨어 의존인데 단정 | "실측 확정(LT 사전 단계), 미달 시 차량 수 상향/합성 보정" 한정 | **fixed** |
| B-1 | critic | **BLOCKER** | §16.1·§15 | Phase 1 "로컬 수집→Bronze"의 실행 스펙 부재(DirectRunner? 로컬 Iceberg 카탈로그? emulator 한계) — 구현자가 첫 주에 멈춤 | Phase 1 로컬 스펙: DirectRunner + Hadoop catalog(로컬 FS) → prod(BigLake) 전환 매트릭스 + Pub/Sub emulator 스키마 미지원→클라이언트측 검증 대체 명기 | **fixed** |
| M-1c | critic | MAJOR | §16.1↔README | Phase 정의 상충(SDD 3-Phase vs README 5-Phase) — 정본 미선언 | README 5-Phase 정본 선언, §16.1 매핑 정합화 | **fixed** |
| M-2c | critic | MAJOR | §6.5·§7.3·§7.2·§6.7 | dim_vehicle이 seed/SQL 모델 상충 + enrich side-input 계약 부재 + 미등록 판정 순환 | dim_vehicle=정적 seed CSV 확정, §7.3 트리 수정, §7.2 side-input 로드·갱신 주기 명시 | **fixed** |
| M-3c | critic | MAJOR | §6.4.1 | "message_id 보조"의 조작적 의미 불명 | "message_id=Dataflow 내장 재전달 제거(코드 없음), event_id=명시적 Beam Deduplicate" 분리 명기 | **fixed** |
| M-4c | critic | MAJOR | §15·G-3 | p99 측정 프로토콜 미정 | §15 Load에 쿼리 종류·계측 지점·CO 회피·sustained 판정 기준 명시 | **fixed** |
| M-5c | critic | MAJOR | §15·§14 | 유실 0 대사 절차 부재 + §14 G-4/G-5 행 없음 | §15 카운트 대사 절차 + §14 행 추가 | **fixed** |
| M-6c | critic | MAJOR | §4.1 관측성 | OTel·Prom·Grafana·Loki 4종 과설계(배포 위치·비용 미정) | 기본 Cloud Monitoring/Logging, 자체 스택은 로컬 개발 한정 축소 | **fixed** |
| M-7c | critic | MAJOR | §8.1·ADR-008 | Pub/Sub 스키마 운영 계약 부재 + emulator 미지원 미기술 | §8.1 연결=yes·BINARY·리비전 절차, §15 로컬 대체 검증 | **fixed** |
| m-1c | critic | MINOR | dlq-envelope.avsc | 싱크 write 실패용 error_class 부재 | enum SINK_WRITE_FAILURE 추가 + §6.7 정합 | **fixed** |
| m-2c | critic | MINOR | §5.2 PNG | 구버전 다이어그램 — 로드맵 체크박스 승격 | §16·README 로드맵 항목화 | **fixed** |
| m-3c | critic | MINOR | §15 | late 데이터 자연 발생 없음 → 지연 주입 시나리오 필요 | §15 Chaos에 생성기 delay 주입 추가 | **fixed** |
| m-4c | critic | MINOR | §9.1 | 최대 부하시험 월 합계 미제시 | 상한 시나리오 1행 추가 | **fixed** |
| m-5c | critic | MINOR | §7.4 | dbt_hourly 센서 방식 모호 | 단순 스케줄+freshness 검사 확정 | **fixed** |
| m-6c | critic | MINOR | §7.1 | 가속 컨테이너 CPU 실현성 — m2 동일 계열 | m2와 통합(캘리브레이션 스텝) | **fixed** |
| M1a | architect | MAJOR | §6.7 | 재처리 절차가 SINK_WRITE_FAILURE와 모순("미도달" 전제) | error_class별 분기(검증실패 3종 한정 + SINK는 §5.2 경로) | **fixed** |
| M2a | architect | MAJOR | §7.4↔§5.2 | backfill 입력 소스 불일치(Bronze vs dlq/bq/) | Bronze 리플레이=정본 소스 확정, dlq/bq/=대사 증거 | **fixed** |
| M3a | architect | MAJOR | §7.2↔§16.1 | side-input 부트스트랩 공백(dim은 P3, 잡은 P2) | P2 착수 전 dim seed 선행 + 로컬 CSV fallback | **fixed** |
| m1a-m5a | architect | MINOR | §6.7·§7.2·README·avsc | 분류 4종 헤더·dlq/bq/ 열거·관측성 정합·schemas/ 트리·event_time doc | 전량 반영(README TODO 인용문만 유저 몫 잔존) | **fixed** |

## 듀얼 리뷰 교차 비교 (gemini vs claude)

| 관점 | gemini(외부) | claude(critic/architect 레인) | 일치 여부 |
|---|---|---|---|
| 3-way 싱크 커플링 | BLOCKER — BQ 실패 전환 메커니즘 부재 | architect major M2(§7.4 backfill 소스 불일치 — 동일 계열 전파 누락) | ✅ 일치(양쪽 반영: dlq/bq/ 비동기 백필+Bronze 리플레이 확정) |
| 비용 추정 | MAJOR — SE 과금 누락 | critic minor m-4(최대 월 합계 미제시) | ✅ 일치(§9.1 수치화+상한 시나리오 $201) |
| exactly-once 정직성 | MINOR — 용어 정밀화 권고 | cartesian M1(event_id 유일성 테스트 부재 — 더 깊은 지점 검출) | ◐ 상보(용어+테스트 양쪽 반영) |
| 실행가능성 | (미지적) | critic BLOCKER B-1(P1 로컬 실행 스펙 부재) — claude 레인만 검출 | ◑ claude 우위(§16.1 로컬 스펙 신설) |
| 강점 평가 | ADR 체계·ES 사본 원칙·정직한 리스크 관리 | architect strengths: 정직한 한계 문서화·비용-운영 모델 결합·ADR 삼각 정합 | ✅ 일치 |

> 결론: 외부(gemini)와 내부(claude 4레인) 검토가 상호 보완적으로 서로 다른 결함을 검출 — 총 30건 전량 반영, blocker/major 잔존 0. SDD v1.0 확정(리비전 히스토리 참조).
