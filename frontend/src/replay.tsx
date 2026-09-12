import { createRoot } from "react-dom/client";
import { SensorViewer } from "./components/SensorViewer";
import "./styles/replay.css";

const requested = new URLSearchParams(location.search).get("scene") ?? "scene-0061";
const scene = /^scene-\d{4}$/.test(requested) ? requested : "scene-0061";

createRoot(document.getElementById("root")!).render(
  <main>
    <header>
      <h1>FleetSentinel · {scene}</h1>
      <p>nuScenes 실데이터 · 카메라 / LiDAR / 3D 객체 / CAN 신호</p>
      <small>기록된 센서 데이터 재생 — 실시간 이상 탐지 결과나 처리 성능을 나타내는 화면이 아닙니다.</small>
    </header>
    <SensorViewer rrdUrl={`/rrd/${scene}.rrd`} />
  </main>,
);
