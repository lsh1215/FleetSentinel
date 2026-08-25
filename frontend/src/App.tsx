import { useEffect, useRef, useState } from "react";
import { SseClient, type StreamStatus } from "./lib/sse";
import { telemetryStore } from "./lib/telemetryStore";
import { FleetMap } from "./components/FleetMap";
import { SignalChart } from "./components/SignalChart";
import { EventFeed } from "./components/EventFeed";
import { VehicleList } from "./components/VehicleList";
import { PipelineHealth } from "./components/PipelineHealth";
import { ClipSearch } from "./components/ClipSearch";
import { SensorPanel } from "./components/SensorPanel";

interface VehicleMeta {
  vehicle_id: string;
  scene_name: string;
  location: string;
  description: string;
}

export default function App() {
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [selected, setSelected] = useState<string | null>(null);
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
        <div className="top-meta">
          {selectedMeta && (
            <span className="scene">
              <b>{selectedMeta.vehicle_id}</b> · {selectedMeta.scene_name} · {selectedMeta.location}
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
          <div className="map-wrap">
            <FleetMap selectedId={selected} onSelect={setSelected} />
            {selectedMeta && <p className="map-note">{selectedMeta.description}</p>}
          </div>
          <div className="charts">
            <SignalChart vehicleId={selected} metric="speed" label="속도" unit="m/s" color="#38bdf8" />
            <SignalChart vehicleId={selected} metric="steering" label="조향각" unit="rad" color="#fbbf24" />
            <SignalChart vehicleId={selected} metric="yawRate" label="yaw rate" unit="rad/s" color="#a78bfa" />
          </div>
          <SensorPanel vehicleId={selected} rrdUrl={rrdUrl} />
        </section>

        <aside className="col right">
          <EventFeed onSelect={setSelected} />
          <ClipSearch onSelect={setSelected} />
        </aside>
      </main>
    </div>
  );
}
