import { useEffect, useRef, useState } from "react";
import { SseClient, type StreamStatus } from "./lib/sse";
import { telemetryStore } from "./lib/telemetryStore";
import { FleetMap } from "./components/FleetMap";
import { SignalChart } from "./components/SignalChart";
import { EventFeed } from "./components/EventFeed";
import { VehicleList } from "./components/VehicleList";
import { PipelineHealth } from "./components/PipelineHealth";
import { KpiStrip } from "./components/KpiStrip";
import { ClipSearch } from "./components/ClipSearch";
import { SensorViewer } from "./components/SensorViewer";

interface VehicleMeta {
  vehicle_id: string;
  scene_name: string;
  location: string;
  description: string;
}

export default function App() {
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"map" | "sensor">("map");
  const [reloadKey, setReloadKey] = useState(0);
  const [meta, setMeta] = useState<VehicleMeta[]>([]);
  const clientRef = useRef<SseClient | null>(null);

  // 로스터를 먼저 받아 차량 메타(지역·장면)를 저장소에 심어둔다.
  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/vehicles", { signal: ctrl.signal })
      .then((r) => r.json())
      .then((m: { vehicles: VehicleMeta[] }) => {
        setMeta(m.vehicles);
        for (const v of m.vehicles) {
          telemetryStore.ensureVehicle(v.vehicle_id, {
            location: v.location,
            sceneName: v.scene_name,
          });
        }
        setSelected((cur) => cur ?? m.vehicles[0]?.vehicle_id ?? null);
      })
      .catch(() => {});
    return () => ctrl.abort();
  }, []);

  // SSE 연결. 핸들러는 저장소에 쓰기만 하고 setState를 호출하지 않는다 —
  // 초당 수천 건이 들어오므로 여기서 렌더를 유발하면 즉시 무너진다.
  useEffect(() => {
    const client = new SseClient({
      url: "/api/stream",
      onStatus: setStatus,
      pauseWhenHidden: true,
      handlers: {
        signal: (d) => telemetryStore.ingestSignals(d as never),
        perception: (d) => telemetryStore.ingestPerception(d as never),
        epoch: () => telemetryStore.markEpoch(),
      },
    });
    clientRef.current = client;
    client.start();
    return () => client.stop();
  }, []);

  const selectedMeta = meta.find((m) => m.vehicle_id === selected);
  const rrdUrl = selectedMeta ? `/rrd/${selectedMeta.scene_name}.rrd` : null;

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo" />
          <div>
            <h1>FleetSentinel Console</h1>
            <p>자율주행 fleet 관제 · 실측 nuScenes 재생</p>
          </div>
        </div>
        <KpiStrip />

        <div className="top-meta">
          {selectedMeta && (
            <span className="scene">
              {selectedMeta.scene_name} · {selectedMeta.location}
            </span>
          )}
          <span className={`badge s-${status}`}>{status}</span>
        </div>
      </header>

      <main className="grid">
        <aside className="col left">
          <VehicleList selectedId={selected} onSelect={setSelected} />
          <PipelineHealth streamStatus={status} />
        </aside>

        <section className="col center">
          <div className="view-tabs">
            <button className={view === "map" ? "vt on" : "vt"} onClick={() => setView("map")}>
              fleet 지도
            </button>
            <button className={view === "sensor" ? "vt on" : "vt"} onClick={() => setView("sensor")}>
              센서 재생
              <i>카메라 6 · LiDAR · 3D 박스</i>
            </button>
            {view === "sensor" && rrdUrl && (
              <button className="ghost vt-reload" onClick={() => setReloadKey((k) => k + 1)}>
                다시 로드
              </button>
            )}
          </div>

          <div className="stage">
            {/* 지도는 언마운트하지 않는다 — 다시 만들면 타일을 새로 받고 궤적이 끊긴다.
                탭 전환은 표시 여부만 바꾼다. */}
            <div className="stage-layer" style={{ visibility: view === "map" ? "visible" : "hidden" }}>
              <FleetMap selectedId={selected} onSelect={setSelected} />
              {selectedMeta && <p className="map-note">{selectedMeta.description}</p>}
            </div>

            {/* 반대로 뷰어는 탭을 벗어나면 언마운트한다 — wasm이 GPU·메모리를 계속 쥔다. */}
            {view === "sensor" && (
              <div className="stage-layer">
                {rrdUrl ? (
                  <SensorViewer rrdUrl={rrdUrl} reloadKey={reloadKey} />
                ) : (
                  <p className="empty">
                    <b>{selected ?? "차량"}</b>의 재생 파일이 없다.<br />
                    <span className="muted">
                      <code>replay_rerun.py</code>로 <code>.rrd</code>를 만들어{" "}
                      <code>frontend/public/rrd/</code>에 둔다.
                    </span>
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="charts">
            <SignalChart vehicleId={selected} metric="speed" label="속도" unit="m/s" color="#e8eaed" />
            <SignalChart vehicleId={selected} metric="steering" label="조향각" unit="rad" color="#a8b0bd" />
            <SignalChart vehicleId={selected} metric="yawRate" label="yaw rate" unit="rad/s" color="#7f8895" />
          </div>
        </section>

        <aside className="col right">
          <EventFeed onSelect={setSelected} />
          <ClipSearch onSelect={setSelected} />
        </aside>
      </main>
    </div>
  );
}
