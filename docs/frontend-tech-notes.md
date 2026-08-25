# 프론트엔드 기술 정리 — 예상 질문과 근거

> 면접관이 이 대시보드를 보고 **파고들 만한 기술적 지점**을 정리한다. 총 24항목.
> 스타일링·레이아웃처럼 판단이 걸리지 않는 것은 다루지 않는다. 각 항목은
> **질문 → 왜 묻는가 → 답 → 코드 위치** 순이다.
>
> 구현: [`frontend/`](../frontend) · 실행 방법: [`frontend/README.md`](../frontend/README.md)

**검증 상태** — 순수 로직 단위 테스트 **18건**(`npm test`), 타입 체크·프로덕션 빌드 통과,
SSE 스트림·재개 실측 확인. GL·캔버스 렌더는 육안 확인이 필요하다.

**전제가 되는 수치** — 차량 4대 재생 기준 **초당 약 5,100 레코드 / 약 39 배치**가 들어온다.
실측값이며 [데이터 설계 §3](data-design.md)이 정본이다. 이 숫자가 아래 대부분의 판단을 만든다.

---

## 1. 실시간 연결

### Q1. 왜 WebSocket이 아니라 SSE인가?

**왜 묻나** — 실시간이라고 하면 반사적으로 WebSocket을 떠올린다. 다른 선택을 했다면 근거가
있어야 한다.

**답**

이 화면의 데이터 흐름은 **서버 → 클라이언트 단방향**뿐이다. 클라이언트가 서버로 보내는 것은
차량 선택·클립 검색 같은 요청인데, 그건 REST로 충분하고 실시간일 필요도 없다.

| | WebSocket | **SSE (채택)** |
|---|---|---|
| 방향 | 양방향 | 서버→클라이언트 |
| 프로토콜 | HTTP 업그레이드, 별도 핸들링 | 그냥 HTTP |
| 재연결 | **직접 구현** | 브라우저 내장 + `Last-Event-ID` |
| 프록시·인프라 | 업그레이드 지원 필요 | HTTP라 그대로 통과 |
| 재개(resume) | 직접 설계 | **표준에 있음** |

결정적인 것은 **재개**다. SSE는 서버가 `id:` 필드를 실어 보내면 브라우저가 재연결 시
`Last-Event-ID` 헤더를 자동으로 붙인다. WebSocket으로 같은 걸 하려면 시퀀스 번호 관리와
재개 핸드셰이크를 직접 만들어야 한다. 양방향이 필요 없는데 그 비용을 낼 이유가 없다.

**바뀔 조건** — 브라우저에서 차량으로 명령을 보내야 하면(원격 정지·경로 지시) 그때는
WebSocket이 맞다. 지금 요구에 그게 없다.

📄 `src/lib/sse.ts` · `server/mockStream.ts`

---

### Q2. `EventSource`가 자동 재연결을 해주는데 왜 직접 감쌌나?

**왜 묻나** — 표준 API가 해주는 일을 다시 만들었다면 십중팔구 이유가 있거나, 아니면
바퀴를 다시 발명한 것이다. 어느 쪽인지 확인하려는 질문이다.

**답**

`EventSource`의 자동 재연결로는 **세 가지가 안 된다.**

**① 재연결 간격을 제어할 수 없다.** 서버가 죽으면 브라우저가 고정 간격으로 계속 두드린다.
탭이 여러 개면 동시에 두드려 서버가 살아나는 순간 다시 넘어진다. 그래서 **지수 백오프 +
지터**를 얹었다.

```ts
const backoff = Math.min(max, BASE_DELAY_MS * 2 ** this.attempt);
const jitter = Math.random() * backoff * 0.3;   // 동시 재연결을 흩뜨린다
```

지터가 없으면 여러 클라이언트가 **같은 순간에** 재시도해 같은 문제가 반복된다.

**② 연결 상태를 구분할 수 없다.** `EventSource`는 `onerror` 하나뿐이라 "끊김"과 "재시도 중"을
구별하지 못한다. 관제 화면에서 이건 중요하다 — **지도의 차가 안 움직이는 게 정체인지 연결이
끊긴 건지** 사용자가 알아야 한다. 그래서 `connecting / open / retrying / closed` 상태를
밖으로 노출하고 헤더 배지에 그대로 표시한다.

**③ 백그라운드 탭 문제.** 탭이 숨겨져도 계속 받는다. 5분 뒤 돌아오면 수십만 건이 밀려
프레임이 멈춘다. 그래서 `visibilitychange`에 연결해 **숨으면 끊고, 돌아오면 재개**한다.
재생 스트림이라 중간을 건너뛰어도 무방하고, 실제 관제에서도 "안 보던 동안의 과거"보다
"지금 상태"가 중요하다.

📄 `src/lib/sse.ts`

---

### Q3. 끊겼다 붙었을 때 데이터가 빠지거나 겹치지 않는 건 어떻게 보장하나?

**왜 묻나** — 재연결을 말했으면 반드시 따라오는 질문이다. 여기서 "브라우저가 알아서 해줍니다"만
답하면 재개를 이해 못 한 것이다.

**답**

**커서를 클라이언트가 관리하지 않는다.** 서버가 매 이벤트에 `id:`로 재생 커서(ms)를 싣고,
브라우저가 재연결할 때 그 값을 `Last-Event-ID` 헤더로 자동 전송한다. 서버는 그 지점 이후부터
다시 흘린다.

```
서버 → id: 12400 / event: signal / data: {...}
      (연결 끊김)
브라우저 → GET /api/stream   Last-Event-ID: 12400
서버 → 12400 이후부터 재개
```

직접 커서를 세면 **"어디까지 화면에 반영했나"와 "어디까지 받았나"가 어긋날 때** 버그가 난다.
표준이 주는 걸 쓰는 편이 안전하다.

다만 **최초 연결에는 헤더를 못 넣는다** — `EventSource` 생성자가 헤더를 받지 않기 때문이다.
그래서 우리가 아는 마지막 id가 있으면 쿼리(`?from=`)로 넘기고, 이후 자동 재연결은 브라우저의
헤더에 맡긴다. 서버는 둘 다 받는다.

**중복은 어차피 하류에서 걸러진다.** 모든 레코드가 `event_id`를 갖고 있어 파이프라인이
`keyBy(event_id)`로 중복을 제거한다. 프론트가 완벽할 필요가 없다는 뜻이고, 이건 우연이 아니라
[설계상 그렇게 잡은 것](sdd.md)이다.

📄 `src/lib/sse.ts` `connect()` · `server/mockStream.ts` `/api/stream`

---

## 2. 고빈도 데이터와 React — **이 프로젝트의 핵심**

### Q4. 초당 5,000건이 들어오는데 React가 어떻게 버티나?

**왜 묻나** — 이 대시보드에서 가장 어려운 문제이고, 실시간 데이터를 다뤄본 사람이라면 반드시
묻는다. 여기서 "React Query 씁니다"류로 답하면 문제를 이해 못 한 것이다.

**답**

**버틸 수 없다. 그래서 React를 그 경로에서 뺐다.**

배치로 줄여도 초당 39건이 도착한다. 이걸 `setState`에 연결하면 초당 39번 리렌더가 예약되고,
각 렌더가 지도·차트·목록을 전부 건드린다. 프레임 예산이 남지 않는다.

**세 층으로 나눴다.**

```
SSE 수신  ──▶  가변 저장소 (React 밖)  ──┬─▶ 고빈도: rAF에서 직접 읽어 명령형 갱신
 초당 39건      참조로 즉시 쓰기          │           지도·차트 — React 렌더 0회
                setState 없음            │
                                         └─▶ 저빈도: 4Hz 스로틀 알림
                                                     목록·피드 — useSyncExternalStore
```

핵심은 **수신 경로에 `setState`가 하나도 없다는 것**이다.

```ts
handlers: {
  signal: (d) => telemetryStore.ingestSignals(d as never),   // 순수 가변 쓰기
  perception: (d) => telemetryStore.ingestPerception(d as never),
}
```

그리고 **화면 갱신 주기를 데이터 도착 주기에서 완전히 분리**했다.

| 소비자 | 갱신 방식 | 주기 |
|---|---|---|
| 지도 | rAF에서 저장소 읽어 `setData()` | 최대 60Hz, 프레임당 1회 |
| 차트 | rAF에서 링 버퍼 뷰 읽어 `setData()` | 〃 |
| 차량 목록·이벤트 피드 | `useSyncExternalStore` | **4Hz** |
| 파이프라인 상태 | 폴링 | 0.5Hz |

**왜 4Hz인가** — 사람이 숫자가 "살아있다"고 느끼는 최소치이면서, 도착률(39Hz)의 1/10이다.
더 올려도 사람이 못 읽고, 더 낮추면 멈춘 것처럼 보인다.

📄 `src/lib/telemetryStore.ts` · `src/App.tsx`

---

### Q5. `useSyncExternalStore`의 스냅샷으로 왜 숫자를 돌려주나?

**왜 묻나** — 이 훅을 실제로 써본 사람만 아는 함정이다. 안 겪어봤으면 못 하는 질문이자,
겪어봤으면 반드시 하는 질문이다.

**답**

```ts
getSnapshot = (): number => this.version;   // 객체가 아니라 숫자
```

`useSyncExternalStore`는 스냅샷을 **`Object.is`로 비교**한다. 여기서 객체를 새로 만들어
돌려주면 매번 참조가 달라 React가 "바뀌었다"고 판단하고, 렌더 중에 다시 스냅샷을 읽어
또 다르고… **무한 렌더에 빠진다.**

```ts
// ❌ 매 호출마다 새 배열 → 무한 렌더
getSnapshot = () => [...this.vehicles.values()];
```

그래서 **스냅샷은 단조 증가하는 버전 번호**만 돌려주고, 실제 데이터는 컴포넌트가 getter로
직접 읽는다.

```tsx
useSyncExternalStore(telemetryStore.subscribe, telemetryStore.getSnapshot); // 구독만
const vehicles = telemetryStore.listVehicles();                             // 데이터는 직접
```

"구독"과 "읽기"를 분리하는 셈이다. 캐시된 스냅샷 객체를 유지하는 방법도 있지만, 데이터가
초당 수천 번 바뀌는 여기서는 캐시 무효화 비용이 더 크다.

📄 `src/lib/telemetryStore.ts` `getSnapshot` · `src/components/VehicleList.tsx`

---

### Q6. 지도와 차트가 React 렌더 없이 갱신된다는 게 무슨 뜻인가?

**왜 묻나** — Q4의 답을 진짜로 구현했는지 확인하는 후속 질문이다.

**답**

두 컴포넌트 모두 **마운트 이후 React가 다시 그리지 않는다.** 자기 `requestAnimationFrame`
루프를 돌면서 저장소를 직접 읽고 GL/캔버스를 명령형으로 갱신한다.

```tsx
useEffect(() => {
  const tick = () => {
    rafRef.current = requestAnimationFrame(tick);
    const vehicles = telemetryStore.listVehicles();   // React 밖에서 읽는다
    source.setData({ type: "FeatureCollection", features: points });  // 직접 갱신
  };
  rafRef.current = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(rafRef.current);
}, []);   // ← 의존성 비어 있음
```

**의존성 배열이 비어 있는 것이 의도다.** `selectedId`를 넣으면 선택이 바뀔 때마다 지도가 통째로
재생성되어 타일을 다시 받는다. 대신 **ref로 최신값을 읽는다**.

```tsx
const selectedRef = useRef(selectedId);
selectedRef.current = selectedId;   // 렌더마다 갱신, 이펙트는 재실행 안 됨
```

이건 "props를 이펙트에서 쓰려면 의존성에 넣어라"는 일반 규칙의 **의도적 예외**다. 규칙의 목적이
"낡은 값 참조 방지"인데, ref는 항상 최신을 보므로 목적은 충족하면서 재생성만 피한다.

**rAF의 부수 효과 하나** — 브라우저가 백그라운드 탭에서 rAF를 멈춘다. 안 보이는 화면을 그리지
않는 최적화가 공짜로 따라온다.

📄 `src/components/FleetMap.tsx` · `src/components/SignalChart.tsx`

---

### Q7. 분리가 실제로 되고 있는지 어떻게 확인했나?

**왜 묻나** — 설계를 말했으면 검증을 묻는다. "그럴 것 같습니다"와 "재봤습니다"는 다르다.

**답**

저장소가 **자체 계측**을 한다. 1초 창으로 수신 레코드/배치를 세어 화면에 표시한다.

```ts
recordsPerSec = Math.round((this.windowRecords * 1000) / dt);
```

파이프라인 패널의 `수신 처리량`이 그 값이다. 실측으로 **초당 약 5,100 rec / 39 batch**가
찍히는데, 이 수치가 유지되면서 화면이 부드럽다는 것이 곧 분리가 동작한다는 증거다.

수치 자체도 서버 쪽에서 독립적으로 확인했다.

```
3초 수신 → signal 116건 · perception 25건 · 레코드 15,421건  ≈ 초당 5,140
```

📄 `src/lib/telemetryStore.ts` `tickThroughput` · `src/components/PipelineHealth.tsx`

---

## 3. 메모리와 자료구조

### Q8. 시계열을 계속 받는데 메모리는 어떻게 관리하나?

**왜 묻나** — 장시간 켜두는 관제 화면에서 반드시 터지는 지점이다. 배열에 `push`만 하는
구현은 몇 분이면 무너진다.

**답**

**고정 크기 링 버퍼**를 쓴다. 가장 오래된 값을 덮어써서 길이가 상수로 유지된다.

```ts
push(x: number, y: number): void {
  this.xs[this.head] = x;
  this.ys[this.head] = y;
  this.head = (this.head + 1) % this.capacity;   // 순환
  if (this.count < this.capacity) this.count += 1;
}
```

**세 가지 선택이 붙어 있다.**

**① `TypedArray`(Float64Array)를 쓴다.** 일반 배열은 요소마다 박싱될 수 있고 GC 대상이다.
`Float64Array`는 연속 메모리라 GC 압력이 없고 캐시 지역성도 좋다.

**② 열 지향으로 저장한다.** uPlot이 `[xs[], ys[]]` 형태를 요구한다. 객체 배열
(`{x, y}[]`)로 들고 있다가 매 프레임 변환하면 **그 변환이 병목**이 된다. 처음부터 필요한
형태로 둔다.

**③ 정렬된 뷰를 캐시한다.** 링 버퍼는 물리적으로 순환하므로 그대로 넘기면 차트가 뒤엉킨다.
한 번 펴줘야 하는데, rAF가 초당 60번 호출하므로 **버퍼가 안 바뀌었으면 이전 결과를 재사용**한다.

```ts
view(): [Float64Array, Float64Array] {
  if (!this.viewDirty) return [this.subarrayX, this.subarrayY];   // 재사용
  ...
}
```

**용량 산정** — 900개. `ego_pose`가 20Hz이므로 약 45초 창이다. 관제에서 보는 시간 범위로
충분하고, 900 × 8바이트 × 2 = 14KB에 불과하다.

📄 `src/lib/ringBuffer.ts`

---

### Q9. 궤적 배열에 `shift()`를 쓰던데 O(n) 아닌가?

**왜 묻나** — 코드를 실제로 읽은 사람만 하는 질문이다. 알고 썼는지 모르고 썼는지가 갈린다.

**답**

**맞다. 알고 쓴 타협이다.**

```ts
v.trail.push([lon, lat]);
if (v.trail.length > TRAIL_MAX) v.trail.shift();   // O(n), n=400
```

`shift()`는 O(n)이고 여기서 n은 400이다. `ego_pose`가 20Hz이므로 **초당 20번 × 400 원소
이동**이고, 이건 프레임 예산에서 무시할 수준이다.

링 버퍼로 바꾸지 않은 이유는 **소비 형태가 다르기 때문**이다. 궤적은 MapLibre에 GeoJSON
`LineString` 좌표 배열로 통째 넘겨야 해서, 어차피 매 프레임 정렬된 일반 배열이 필요하다.
링 버퍼를 쓰면 매번 펴주는 비용이 추가된다.

**바뀔 조건** — 차량이 수백 대가 되면 `400 × N`이 되므로 그때는 링 버퍼 + 뷰 캐시로 바꾸거나,
애초에 궤적을 서버에서 단순화(Douglas-Peucker)해 내려받는 편이 낫다.

📄 `src/lib/telemetryStore.ts` `ingestSignals`

---

## 4. 지도 렌더링

### Q10. 왜 `maplibregl.Marker`를 안 쓰고 GeoJSON 소스를 쓰나?

**왜 묻나** — 튜토리얼은 대부분 Marker를 쓴다. 다르게 했다면 이유가 있어야 한다.

**답**

`Marker`는 **차량마다 DOM 노드를 만들고** 매 프레임 `transform`을 갱신한다. 4대면 아무
문제 없지만 수백 대가 되면 레이아웃·합성 비용이 선형으로 늘고, 지도를 드래그할 때 모든
노드가 함께 움직여 프레임이 무너진다.

대신 **GeoJSON 소스 하나에 전 차량을 담고 GL 레이어로 그린다.**

```ts
map.addSource("vehicles", { type: "geojson", data: EMPTY });
map.addLayer({ id: "vehicles", type: "circle", source: "vehicles", paint: {...} });
// 갱신은 통째로
source.setData({ type: "FeatureCollection", features: points });
```

렌더는 GPU가 하고, **차량 수가 늘어도 드로우콜은 그대로**다. 색·크기 분기는 데이터 드리븐
스타일로 처리해서 자바스크립트가 개입하지 않는다.

```ts
"circle-color": ["case", ["get", "harsh"], "#ef4444", "#38bdf8"]
```

**`setData`를 매 프레임 부르는 게 비싸지 않나** — 피처 수가 차량 수(수십)라 직렬화 비용이
작다. 수만 개가 되면 그때는 `deck.gl`의 GPU 버퍼 갱신이나 벡터 타일로 가야 한다.
지금 규모에서 `setData`는 충분히 싸고, 구조가 단순해 유지비가 낮다.

📄 `src/components/FleetMap.tsx`

---

## 5. 좌표 — 조용히 틀리는 버그

### Q11. lat/lon 순서 문제를 어떻게 다뤘나?

**왜 묻나** — 지도 다뤄본 사람은 반드시 한 번 당한다. 당해봤는지, 대책이 있는지를 본다.

**답**

**GeoJSON·MapLibre는 `[lon, lat]`이고, 사람 표기와 대부분의 DB 함수는 `(lat, lon)`이다.**
뒤바뀌면 **에러가 안 나고 엉뚱한 대륙에 점이 찍힌다.** 조용히 틀리는 종류라 더 위험하다.

두 가지로 막았다.

**① 타입으로 구분한다.**

```ts
export type LatLon = readonly [lat: number, lon: number];
export type LonLat = readonly [lon: number, lat: number];
```

명명된 튜플이라 IDE에서 어느 쪽인지 보이고, 변환은 이름 붙은 함수로만 한다.

**② 값 범위로 즉시 잡는다.**

```ts
if (Math.abs(lat) > 90) {
  throw new Error(`위도 ${lat}는 ±90을 벗어난다 — lat/lon 순서가 뒤바뀐 것으로 보인다`);
}
```

**위도는 물리적으로 ±90을 넘을 수 없다.** 넘었다면 경도가 들어온 것이다. 이 한 줄이
"싱가포르(경도 103)"를 즉시 잡아낸다.

**왜 조용히 바꿔치지 않았나** — 자동 교정하면 진짜 버그가 숨는다. 데이터 소스가 규약을
어긴 것인데 화면만 멀쩡해 보이면 원인을 못 찾는다. **시끄럽게 실패하는 편이 낫다.**

📄 `src/lib/geo.ts` · `src/lib/telemetryStore.ts`

---

## 6. 번들과 로딩

### Q12. Rerun 뷰어 wasm이 29.8MB인데 초기 로딩은 어떻게 했나?

**왜 묻나** — 숫자가 눈에 띄게 크다. 이걸 그냥 뒀다면 성능 감각이 없는 것이다.

**답**

**동적 `import()`로 코드 분할해 사용자가 열 때만 내려받는다.**

```tsx
const RerunViewer = lazy<ComponentType<RerunProps>>(async () => {
  const mod = await import("@rerun-io/web-viewer-react");
  return { default: mod.default as unknown as ComponentType<RerunProps> };
});
```

그리고 **패널을 열기 전까지는 `lazy` 컴포넌트를 렌더하지 않는다.** `lazy`는 렌더되는 순간
로드를 시작하므로, `open` 상태를 두어 사용자가 명시적으로 열 때만 트리거한다.

빌드 결과로 분리가 확인된다.

```
dist/assets/re_viewer_bg-*.wasm   29,778 kB  (gzip 9,650 kB)   ← 별도 청크, 요청 시에만
dist/assets/maplibre-*.js          1,053 kB  (gzip   285 kB)
dist/assets/react-*.js               192 kB  (gzip    60 kB)
dist/assets/charts-*.js               52 kB  (gzip    23 kB)
dist/assets/index-*.js                38 kB  (gzip    14 kB)   ← 우리 앱 코드
```

**벤더를 따로 쪼갠 이유**는 캐시다. 앱 코드는 자주 바뀌지만 MapLibre는 거의 안 바뀐다.
한 청크에 묶으면 앱을 배포할 때마다 사용자가 1.3MB를 다시 받는다. 분리하면 **38KB만**
다시 받는다.

```ts
manualChunks: { maplibre: ["maplibre-gl"], charts: ["uplot"], react: [...] }
```

📄 `vite.config.ts` · `src/components/SensorPanel.tsx`

---

### Q13. 뷰어 버전은 어떻게 관리하나?

**왜 묻나** — 외부 뷰어를 붙였다면 버전 결합이 있는지 확인한다.

**답**

**`.rrd` 포맷이 아직 안정화 전이라 뷰어와 SDK 버전이 결합돼 있다.** 0.23 이후로는 뷰어가
직전 마이너까지 읽을 수 있지만, 그 이상 벌어지면 **오류 없이 빈 화면**이 된다.

그래서 `.rrd`를 만드는 Python SDK(`rerun-sdk==0.23.1`)와 뷰어 패키지
(`@rerun-io/web-viewer-react@0.23.1`)를 **같은 버전으로 핀**했다. 한쪽만 올리지 않는다.

로드 실패에도 대비했다. 뷰어를 못 불러와도 **대시보드 전체가 죽지 않도록** 대체 컴포넌트를
돌려준다 — 부수적인 패널 하나 때문에 관제 화면이 멈추면 안 된다.

📄 `src/components/SensorPanel.tsx` · `exploration/requirements.in`

---

## 7. 목록 렌더링

### Q14. 이벤트 피드에 가상 스크롤을 쓴 이유는?

**왜 묻나** — 지금 보이는 건 수십 건뿐이다. 과한 것 아니냐고 물을 수 있다.

**답**

이벤트는 최대 300건까지 쌓이고, 저장소가 **4Hz로 알릴 때마다** 목록이 리렌더된다. 전부
DOM으로 만들면 초당 4번 × 300개 노드를 diff하게 된다.

보이는 만큼만 렌더한다.

```tsx
const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
const visible = Math.ceil(height / ROW_HEIGHT) + OVERSCAN * 2;
const slice = events.slice(first, first + visible);
```

`OVERSCAN`은 위아래 여유분이다. 없으면 빠르게 스크롤할 때 빈 공간이 보인다.

**라이브러리를 안 쓴 이유** — 고정 높이 단일 목록이라 30줄이면 되고, `react-window` 같은
의존성을 추가할 만큼 복잡하지 않다. 가변 높이나 중첩이 생기면 그때 도입하는 게 맞다.

**실제 관제에서는 필수다.** 이벤트가 수천~수만 건 쌓이는 게 정상이라, 지금 규모에서 과해
보이더라도 구조를 미리 맞춰두는 편이 낫다.

📄 `src/components/EventFeed.tsx`

---

## 8. 실패 처리

### Q15. 이벤트 하나가 깨지면 어떻게 되나?

**왜 묻나** — 스트림 처리에서 부분 실패를 어떻게 다루는지는 성숙도를 보여준다.

**답**

**한 건이 깨져도 스트림을 끊지 않는다.**

```ts
try {
  handler(JSON.parse(me.data), me.lastEventId || null);
} catch (err) {
  console.warn(`[sse] ${name} 파싱 실패`, err);   // 로그만 남기고 계속
}
```

파싱 실패로 예외가 새어나가면 `EventSource`가 끊기고 재연결 사이클이 돈다. 한 건 때문에
전체 스트림을 잃는 건 손해가 크다.

**폴링도 같은 원칙이다.** `/api/health` 실패는 조용히 넘기고 다음 주기에 재시도한다.
상태 표시가 잠깐 멈추는 것과, 에러 화면이 뜨는 것 중 전자가 낫다.

**단, 조용한 실패를 무한정 허용하지는 않는다.** 연결 상태는 배지로 항상 노출되므로
스트림이 끊긴 것은 사용자가 즉시 안다. **"화면이 안 변한다"와 "연결이 끊겼다"를 구별할 수
있게 하는 것**이 원칙이다.

📄 `src/lib/sse.ts` · `src/components/PipelineHealth.tsx`

---

### Q16. 왜 파이프라인 상태는 스트림이 아니라 폴링인가?

**왜 묻나** — 실시간 스트림을 만들어놓고 일부는 폴링이면 일관성이 없어 보인다.

**답**

**두 데이터가 성격이 다르기 때문**이고, 이건 프론트만의 판단이 아니라
[시스템 설계](sdd.md)에서 나온 구분이다.

| | 제품 데이터 (텔레메트리) | 운영 메트릭 (파이프라인 상태) |
|---|---|---|
| 발생률 | 초당 수천 건 | 초당 1건도 안 됨 |
| 유실 허용 | 불가 — 유실 0이 계약 | 허용 |
| 전달 | **SSE** | **폴링 2초** |

Kafka lag이나 체크포인트 시간은 초당 수천 번 바뀌지 않는다. 스트림에 실으면 연결을 하나 더
쓰거나 이벤트 타입을 섞게 되고, 얻는 게 없다. **2초 폴링이 요구를 정확히 만족하는 가장 단순한
방법**이다.

📄 `src/components/PipelineHealth.tsx`

---

## 9. React 세부

### Q17. StrictMode에서 이펙트가 두 번 실행되는데 SSE 연결이 중복되지 않나?

**왜 묻나** — React 18+ 개발 모드의 이중 마운트를 아는지 확인하는 질문이다.

**답**

**정리 함수가 제대로 있으면 문제가 없다.**

```tsx
useEffect(() => {
  const client = new SseClient({ ... });
  client.start();
  return () => client.stop();   // 반드시 정리
}, []);
```

StrictMode는 `마운트 → 언마운트 → 마운트`를 실행한다. 첫 클라이언트가 `stop()`으로 완전히
정리되므로 두 번째만 남는다. `stop()`이 하는 일:

```ts
this.disposed = true;                    // 진행 중인 재시도 무효화
document.removeEventListener(...);       // 리스너 해제
this.clearRetry();                       // 예약된 타이머 취소
this.close();                            // EventSource 닫기
```

**`disposed` 플래그가 중요하다.** 백오프 타이머가 이미 예약돼 있으면 `clearTimeout`만으로는
경합이 남을 수 있어, 콜백 진입 시점에도 한 번 더 확인한다.

지도·차트의 rAF 루프도 같다 — `cancelAnimationFrame`으로 정리하지 않으면 이중 마운트에서
루프가 두 개 돌며 저장소를 중복 읽는다.

📄 `src/App.tsx` · `src/lib/sse.ts` `stop()`

---

## 8-1. 실제로 잡은 버그들

앞의 항목들이 "왜 이렇게 설계했나"라면, 여기는 **만들면서 실제로 터진 것**이다. 면접에서
"어려웠던 점"을 물으면 꺼낼 수 있는 쪽이고, 근거가 코드에 남아 있어 검증 가능하다.

### Q18. Rerun 공식 React 래퍼가 개발 모드에서 빈 화면이었다. 원인이 뭔가?

**왜 묻나** — 서드파티 라이브러리 문제를 소스까지 읽어 진단했는지, 아니면 우회만 했는지 갈린다.

**답**

`@rerun-io/web-viewer-react`의 소스를 열어보니 클래스 컴포넌트이고 생명주기가 이렇다.

```js
constructor()          → this.#handle = new rerun.WebViewer()
componentDidMount()    → startViewer(this.#handle, ...)
componentWillUnmount() → this.#handle.stop()
```

React 19 StrictMode는 개발 모드에서 `mount → unmount → mount`를 **같은 인스턴스에** 실행한다.
그러면 순서가 이렇게 된다.

```
start(handle)  →  handle.stop()  →  start(handle)
                                    ↑ 이미 정지된 핸들
```

**생성자는 다시 돌지 않으므로** 두 번째 `start`가 죽은 핸들을 붙잡는다. wasm 뷰어라 예외도
안 나고 **오류 없는 빈 화면**이 된다.

**해결** — StrictMode는 하위 트리에서 끌 수 없고, 그것 하나 때문에 앱 전체의 StrictMode를
포기하는 건 손해다. 그래서 프레임워크 비의존 패키지(`@rerun-io/web-viewer`)를 이펙트에서
직접 쓴다.

```tsx
useEffect(() => {
  const mod = await import("@rerun-io/web-viewer");
  const instance = new mod.WebViewer();      // 이펙트 실행마다 새 인스턴스
  await instance.start(rrdUrl, host, {...});
  return () => { instance.stop(); host.replaceChildren(); };
}, [rrdUrl, reloadKey]);
```

**StrictMode의 이중 마운트가 정확히 이 패턴을 검증하려고 존재한다.** 정리에서 완전히 버리고
다시 만들면 통과한다. `host.replaceChildren()`도 필요하다 — 뷰어가 만든 canvas가 남으면
다음 마운트에서 겹친다.

📄 `frontend/src/components/SensorViewer.tsx`

---

### Q19. 이벤트가 쌓이면 아래 패널이 화면 밖으로 밀려났다. 왜인가?

**왜 묻나** — 가상 스크롤과 flex를 같이 쓸 때의 함정이고, 겪지 않으면 모른다.

**답**

이벤트 피드가 `flex: 1 1 auto`였다. **`flex-basis: auto`는 기준 크기를 내용에서 가져온다.**

가상 스크롤 구조가 이렇다.

```tsx
<div style={{ height: events.length * ROW_HEIGHT }}>   // 300건이면 13,800px
```

스페이서 div가 이벤트 수에 비례해 자라니 **패널의 flex 기준 크기도 같이 자라** 아래 형제를
밀어냈다. 내부 `overflow-y: auto`가 있어도 소용없다 — **스크롤은 내용을 담아주지만 기준 크기
계산은 막지 못한다.**

```css
.feed { flex: 1 1 0; min-height: 140px; }   /* auto → 0 */
```

`flex-basis: 0`으로 두면 기준이 내용과 무관해지고 남은 공간만 비율로 나눈다. `min-height: 0`도
같이 필요하다 — 없으면 flex 자식이 내용 크기 아래로 줄지 못해 컨테이너를 넘친다.

**같은 함정이 다른 곳에도 있었다.** 차량 목록도 동일 구조라 차량이 늘면 파이프라인 패널을
밀어낼 것이었다. 4대뿐이라 안 드러났지만 N대로 늘리면 똑같이 터진다.

📄 `frontend/src/styles/app.css`

---

### Q20. 줌아웃하면 지도 라벨이 겹쳤다. 어떻게 다뤘나?

**왜 묻나** — 지도를 다뤄본 사람은 라벨 충돌을 반드시 만난다.

**답**

내가 `"text-allow-overlap": true`를 넣어 **MapLibre의 충돌 회피를 껐던 것**이 원인이었다.
라벨을 항상 보이게 하려던 의도였는데, 줌아웃하면 차량이 뭉치면서 라벨이 그대로 쌓인다.

네 가지를 조합해 고쳤다.

```ts
minzoom: 12,                    // 줌 12 미만은 라벨을 그리지 않는다
"text-allow-overlap": false,    // 충돌 회피를 되살린다
"text-optional": true,          // 자리가 없으면 라벨만 생략, 점은 남긴다
"symbol-sort-key": ["case", ["get", "selected"], 0, ["get", "alert"], 1, 2],
```

**`text-optional`이 중요하다.** 기본값이면 라벨이 안 들어갈 때 **아이콘까지 함께 숨긴다** —
차량을 아예 놓치게 된다. `true`로 두면 점은 남고 라벨만 생략된다.

`symbol-sort-key`로 **선택 차량과 경보 차량이 먼저 자리를 차지**하게 했다. 라벨을 하나만 보여야
할 상황에서 무작위로 고르면 하필 관심 없는 차량이 남는다.

그리고 **선택 차량은 별도 레이어**로 분리해 줌과 무관하게 항상 라벨을 보여준다. 지금 보고 있는
대상이 사라지면 안 되기 때문이다.

원과 선 굵기도 줌으로 보간했다.

```ts
"circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2.5, 13, 4, 17, 5.5]
```

줌아웃할수록 점이 작아져 뭉침 자체가 덜 보인다. 고정 크기면 넓은 영역에서 점이 서로 삼킨다.

📄 `frontend/src/components/FleetMap.tsx`

---

### Q21. 색을 거의 안 쓴 이유가 있나?

**왜 묻나** — 디자인 판단을 물으면서 실제로는 "의도가 있나 없나"를 본다.

**답**

**색을 장식이 아니라 상태 전달에만 쓴다.** 팔레트가 셋뿐이다 — 경보(빨강)·주의(노랑)·정상(초록).
그 외는 전부 무채색 명도 단계다.

이유는 단순하다. **평상시 화면이 알록달록하면 경보가 눈에 띄지 않는다.** 관제 화면의 목적은
"이상한 것을 빨리 찾는 것"이고, 그러려면 정상 상태가 조용해야 한다.

선택 상태도 색이 아니라 **명도 + 좌측 마커**로 표현한다.

```css
.vehicle.sel { background: var(--raised); box-shadow: inset 2px 0 0 var(--sel); }
```

**숫자는 전부 monospace + tabular-nums**로 뒀다. 엔지니어는 수치를 읽지 않고 **스캔**하는데,
자리수가 흔들리면 그게 안 된다. 초당 갱신되는 값이라 특히 중요하다 — 폭이 변하면 시선이 흔들린다.

섹션 라벨은 대문자 + 자간이다. 제목과 데이터를 확실히 분리하는 관용구다.

**초기에는 Tailwind 기본 팔레트(sky-400 / violet-400 / emerald-400)를 썼는데 걷어냈다.**
범용 대시보드처럼 보이는 가장 큰 원인이었다.

📄 `frontend/src/styles/app.css`

---

### Q22. 차트 세 개의 커서를 동기화한 이유는?

**왜 묻나** — 작은 기능이지만 도메인 이해가 있는지 드러난다.

**답**

속도·조향각·yaw rate는 **상관된 신호**다. 한 차트에서 t=12.4s를 볼 때 나머지도 같은 시각을
가리켜야 **"감속하면서 조향했다"** 를 읽을 수 있다.

```ts
const cursorSync = uPlot.sync("signals");
cursor: { sync: { key: cursorSync.key } }
```

동기화가 없으면 사람이 눈으로 시각을 맞춰야 하고, **그게 관제에서 가장 흔한 오독 원인**이다.
uPlot이 `sync`를 기본 제공하므로 비용은 두 줄이다.

📄 `frontend/src/components/SignalChart.tsx`

---

### Q22-1. 인지 객체를 지도에 어떻게 투영했나?

**왜 묻나** — 자율주행 관제를 일반 fleet 관제와 구별하는 지점이다. 좌표계를 이해했는지가
바로 드러난다.

**답**

인지 3D 박스는 **글로벌 ENU 미터 좌표**로 온다(`ego_pose`와 같은 프레임). 지도는 WGS84
위경도를 요구하므로 변환이 필요하다.

**세 가지를 풀어야 했다.**

**① 회전을 어디서 뽑나** — 원본은 쿼터니언이다. 브라우저로 쿼터니언 4개를 보내 거기서
yaw를 계산할 수도 있지만, **추출 단계에서 devkit 함수로 계산해 각도 하나만 보낸다.**
정확하고 페이로드도 작다.

```python
"yaw": round(quaternion_yaw(Quaternion(o.rot_w, o.rot_x, o.rot_y, o.rot_z)), 4)
```

**② 중심만 변환하면 박스가 찌그러진다** — 중심을 위경도로 바꾼 뒤 미터 오프셋을 더하면,
위도에 따라 경도 스케일이 달라져 직사각형이 마름모가 된다. 그래서 **ENU 평면에서 네
모서리를 먼저 만들고 각각 변환**한다.

```ts
const local = [[hl, hw], [hl, -hw], [-hl, -hw], [-hl, hw]];   // 로컬 (길이, 폭)
const gx = cx + lx * cos - ly * sin;                          // yaw 회전 후 글로벌 ENU
const p = enuToWgs84(gx, gy, location);                       // 모서리마다 변환
```

**③ 프론트와 백엔드가 같은 원점을 써야 한다** — 어긋나면 **차량과 인지 객체가 서로 다른
위치에 찍힌다.** 값이 조금만 달라도 박스가 도로 옆에 떠 있게 되는데, 화면만 보면 인지
모델이 틀린 것처럼 보인다. 테스트로 고정했다.

```ts
it("백엔드 구현과 같은 값을 낸다", () => {
  // exploration/fleetsentinel_ingest/geo.py 로 검증한 실제 ego_pose 좌표
  const p = enuToWgs84(411.3039349319818, 1180.8903791765097, "singapore-onenorth")!;
  expect(p[0]).toBeCloseTo(1.29882, 4);
});
```

**표현 결정 세 가지**

| 결정 | 이유 |
|---|---|
| 색을 **3종으로 묶음** (취약 도로 사용자 / 차량 / 정적) | nuScenes 카테고리는 23종인데 23색을 쓰면 아무것도 안 보인다. 관제에 필요한 구분은 셋이다 |
| **선택 차량만** 그림 | 전 차량을 동시에 그리면 겹쳐서 "어느 차가 무엇을 보는지"를 알 수 없다 — 그게 이 뷰의 존재 이유인데 |
| 저신뢰(LiDAR 미관측)는 **점선 + 낮은 불투명도** | 숨기면 데이터를 오해한다(23%가 그런 라벨이다). 색만으로 구분하면 색약에서 안 보이므로 점선을 함께 쓴다 |
| 줌 14 미만은 미표시 | 그 아래에서는 객체가 픽셀 몇 개라 정보를 안 주고 화면만 지저분해진다 |

객체를 클릭하면 `LiDAR 포인트 수`·`가시성`이 뜬다. 관제에서 **"저 박스가 왜 저기 있나"**
를 물을 수 있어야 한다.

📄 `frontend/src/lib/geo.ts` `boxFootprint` · `frontend/src/components/FleetMap.tsx`

---

## 9-1. 테스트를 쓰다 잡은 것

### Q23. 프론트엔드에서 테스트할 가치가 있는 부분은 어디인가?

**왜 묻나** — "렌더링이라 테스트하기 어렵다"는 흔한 회피다. 어디가 테스트 가능한지 구분할 수
있는지 본다.

**답**

이 대시보드에서 **순수 로직으로 분리된 것**이 둘이다 — 링 버퍼와 좌표 변환. rAF·GL·캔버스에
얽히지 않아 값만 넣고 확인하면 된다. 18건을 붙였다.

링 버퍼는 **순환 후 `view()`가 시간순으로 펴지는지**와 **변경이 없으면 같은 배열 인스턴스를
재사용하는지**가 핵심이다. 후자는 rAF가 초당 60번 호출하는 경로라 참조 동일성이 깨지면
매 프레임 배열을 새로 만들게 된다.

```ts
const [a] = rb.view();
const [b] = rb.view();
expect(a).toBe(b);          // 참조 동일 — 재사용 확인
rb.push(2, 2);
expect(rb.view()[0]).not.toBe(a);   // 변경 후엔 새로 만든다
```

**그리고 테스트를 쓰다 내 가정이 틀린 걸 발견했다.**

처음에 "같은 위도선을 따라 동쪽으로 가면 방위각 90°"라고 단언했는데 실제로는 **89.70°** 가
나왔다. 구현 버그를 의심했지만 **대권 항로가 극쪽으로 휘기 때문**이었다 — 위도선을 따라가는
경로는 대권이 아니다. 적도에서만 정확히 90°가 된다.

```ts
it("적도에서는 정확히 90도다 — 휨이 사라지는 유일한 위도", () => {
  expect(bearingDeg([0, 127.0], [0, 128.0])).toBeCloseTo(90, 6);
});
```

**코드가 맞고 테스트가 틀린 경우**였다. 지도 관련 코드에서 "직관적으로 이럴 것 같다"가
구면 기하와 어긋나는 대표적인 예라 그대로 테스트에 남겨뒀다.

📄 `frontend/src/lib/__tests__/`

---

## 10. 안 한 것 (정직하게)

면접에서 **"이건 왜 안 했나"** 로 들어올 수 있는 지점들이다. 미리 답을 준비해둔다.

| 안 한 것 | 왜 | 언제 필요해지나 |
|---|---|---|
| **Web Worker에서 파싱** | 현재 JSON 파싱이 프레임 예산 안에 들어온다. 배치 하나가 43KB이고 초당 39개다 | 페이로드가 바이너리(Protobuf/Arrow)가 되거나 도착률이 수백 Hz가 되면 워커로 옮겨야 한다 |
| **백프레셔 신호** | 재생 스트림이라 서버가 속도를 늦출 이유가 없다. 클라이언트가 못 따라가면 탭 가시성으로 끊는다 | 실시간 원천이고 클라이언트가 병목이면 서버에 샘플링 요청을 보내야 한다 |
| **컴포넌트 테스트** | 로직 대부분이 rAF·GL·캔버스에 있어 DOM 단위 테스트 효용이 낮다. 순수 로직(링 버퍼·좌표)은 **18건 커버함**(`npm test`) | 상호작용이 늘면 Playwright로 e2e를 붙이는 편이 낫다 |
| **에러 바운더리** | 패널 단위 실패는 각자 처리한다 | 패널이 늘면 경계를 두는 편이 낫다 |
| **접근성(a11y)** | 관제 화면이라 우선순위를 뒤로 뒀다 | 실제 제품이면 필수다. 지금은 키보드 탐색과 명암비 정도만 지켰다 |
| **인증** | 백엔드가 없어 인증 경계가 아직 없다 | Spring Boot 붙이면 토큰 갱신과 SSE 인증(EventSource가 헤더를 못 넣는 문제)을 풀어야 한다 |

**마지막 항목이 실제로 까다롭다.** `EventSource`는 커스텀 헤더를 못 넣어서 `Authorization`
헤더로 토큰을 보낼 수 없다. 실무에서는 쿠키 인증을 쓰거나, `fetch` + `ReadableStream`으로
SSE를 직접 파싱하는 방식으로 우회한다. 지금 구현은 인증이 없어 문제가 드러나지 않았을 뿐이다.

---

## 부록. 한 장 요약

| 문제 | 선택 | 핵심 이유 |
|---|---|---|
| 실시간 연결 | SSE | 단방향이면 충분 + `Last-Event-ID` 재개가 표준에 있음 |
| 재연결 | 자체 래퍼 | 백오프·지터 제어, 상태 관측, 백그라운드 탭 처리 |
| 초당 5,100건 | React 밖 가변 저장소 | 수신 경로에 `setState` 0개 |
| 고빈도 렌더 | rAF 명령형 갱신 | 지도·차트는 React 렌더 0회 |
| 저빈도 렌더 | `useSyncExternalStore` + 4Hz 스로틀 | 스냅샷은 숫자(무한 렌더 방지) |
| 시계열 메모리 | 링 버퍼 + `Float64Array` | 상수 메모리, GC 압력 없음, 뷰 캐시 |
| 지도 | GeoJSON 소스 + GL 레이어 | 차량 수가 늘어도 드로우콜 일정 |
| 좌표 | 명명 튜플 + 범위 단언 | 조용히 틀리는 버그를 시끄럽게 만듦 |
| 29.8MB wasm | 동적 import + 열 때만 렌더 | 초기 로드에서 완전히 제외 |
| 번들 | 벤더 분리 | 배포 시 38KB만 재다운로드 |
| 목록 | 가상 스크롤 | 4Hz × 300노드 diff 회피 |
