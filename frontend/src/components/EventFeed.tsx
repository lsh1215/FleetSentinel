import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { telemetryStore, type FleetEvent } from "../lib/telemetryStore";

/**
 * 이벤트 피드 — 가상 스크롤.
 *
 * 이벤트는 최대 300건까지 쌓인다. 전부 DOM으로 만들면 스크롤이 무거워지고, 무엇보다
 * 저장소가 4Hz로 알릴 때마다 300개 노드를 diff하게 된다. **보이는 만큼만 렌더**한다.
 *
 * 실제 관제에서는 이벤트가 훨씬 많이 쌓이므로(수천~수만) 이 구조가 필수다.
 */
const ROW_HEIGHT = 46;
const OVERSCAN = 4;

const KIND_META: Record<FleetEvent["kind"], { label: string; cls: string }> = {
  harsh_brake: { label: "급제동", cls: "ev-harsh" },
  sensor_dropout: { label: "센서결손", cls: "ev-drop" },
  low_confidence: { label: "저신뢰라벨", cls: "ev-low" },
  epoch: { label: "재생루프", cls: "ev-epoch" },
};

export function EventFeed({ onSelect }: { onSelect: (id: string) => void }) {
  useSyncExternalStore(telemetryStore.subscribe, telemetryStore.getSnapshot);
  const events = telemetryStore.listEvents();

  const viewportRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(0);

  useEffect(() => {
    if (!viewportRef.current) return;
    const el = viewportRef.current;
    const ro = new ResizeObserver(([e]) => setHeight(e?.contentRect.height ?? 0));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const visible = Math.ceil(height / ROW_HEIGHT) + OVERSCAN * 2;
  const slice = events.slice(first, first + visible);

  return (
    <div className="panel feed">
      <div className="panel-head">
        <h2>이벤트</h2>
        <span className="muted">{events.length}건</span>
      </div>
      <div
        className="feed-viewport"
        ref={viewportRef}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        <div style={{ height: events.length * ROW_HEIGHT, position: "relative" }}>
          {slice.map((ev, i) => {
            const meta = KIND_META[ev.kind];
            return (
              <button
                key={ev.id}
                className={`feed-row ${meta.cls}`}
                style={{ position: "absolute", top: (first + i) * ROW_HEIGHT, height: ROW_HEIGHT }}
                onClick={() => ev.vehicleId !== "-" && onSelect(ev.vehicleId)}
              >
                <span className="feed-kind">{meta.label}</span>
                <span className="feed-body">
                  <b>{ev.vehicleId}</b> {ev.detail}
                </span>
                <span className="feed-t">{(ev.t / 1000).toFixed(1)}s</span>
              </button>
            );
          })}
          {events.length === 0 && <p className="empty">아직 이벤트가 없다</p>}
        </div>
      </div>
    </div>
  );
}
