# frontend — FleetSentinel Console

자율주행 fleet 관제 대시보드. 실측 nuScenes 재생 스트림을 받아 지도·시계열·이벤트·클립 검색을
한 화면에서 보여준다.

**면접 대비 기술 정리는 [`../docs/frontend-tech-notes.md`](../docs/frontend-tech-notes.md)에 있다.**

## 구성

| | |
|---|---|
| 앱 | React 19 + Vite 7 + TypeScript |
| 지도 | MapLibre GL JS — GeoJSON 소스 + GL 레이어 |
| 시계열 | uPlot — 캔버스, 링 버퍼 |
| 센서 재생 | `@rerun-io/web-viewer-react` (지연 로드, wasm 29.8MB) |
| 실시간 | SSE — 자체 재연결·백오프·`Last-Event-ID` 재개 |

## 실행

```bash
npm test           # 순수 로직 단위 테스트 26건 (픽스처 불필요)
npm install
npm run dev        # http://localhost:5173
npm run build      # 프로덕션 빌드
npm run typecheck
```

**픽스처가 먼저 있어야 한다.** 백엔드가 아직 없으므로 Vite 미들웨어가 목 스트림을 제공하는데,
데이터를 지어내지 않고 **실제 nuScenes에서 뽑아 쓴다**.

```bash
cd ../exploration
PYTHONPATH=. ./.venv/bin/python scripts/export_fixture.py \
    --dataroot ../data/nuscenes --out ../frontend/public/fixture --scenes 4
```

센서 재생 패널을 쓰려면 `.rrd`도 필요하다(`public/rrd/<scene>.rrd`).

```bash
PYTHONPATH=. ./.venv/bin/python scripts/replay_rerun.py \
    <mcap> --out ../frontend/public/rrd/scene-0061.rrd --max-lidar-points 12000
```

## 목 서버가 재현하는 백엔드 계약

`server/mockStream.ts` (Vite 플러그인). Spring Boot가 구현할 계약과 같은 모양이다.

| 엔드포인트 | 내용 |
|---|---|
| `GET /api/stream` | SSE. `event:`는 `signal`/`perception`/`epoch`, `id:`에 재생 커서(ms) |
| `GET /api/vehicles` | 차량 로스터 |
| `GET /api/clips` | 클립 카탈로그 (조건 태그 + `blob_uri`) |
| `GET /api/health` | Kafka lag · DLQ · 체크포인트 · ISR |

신호는 **100ms 프레임**으로 묶어 흘린다. 실측 부하가 그대로 재현된다 —
차량 4대 기준 **초당 약 5,100 레코드 / 약 39 프레임**.

> 차량→클라우드 구간에서는 애플리케이션 배치를 **폐기했다**(축적 창 = 유실 창,
> [설계 검토](../docs/ingestion-design-review.md) §4.1). 브라우저 구간의 100ms 프레임은
> **다른 홉의 다른 결정**이다 — 여기서 놓친 것은 ClickHouse에 남아 있고 `Last-Event-ID`로
> 다시 받을 수 있다. 근거는 [기술 정리 Q3-1](../docs/frontend-tech-notes.md).

## 계층 구조

```
SSE 수신  ──▶  telemetryStore (React 밖, 가변)  ──┬─▶ 지도·차트: rAF에서 직접 읽음
 초당 39프레임   setState 없음                     │             (React 렌더 0회)
                                                 └─▶ 목록·피드: 4Hz 스로틀 알림
                                                               (useSyncExternalStore)
```

수신 경로에 `setState`가 하나도 없다. 데이터 도착 주기와 화면 갱신 주기가 완전히 분리된다.
자세한 이유와 대안 비교는 기술 정리 문서에 있다.
