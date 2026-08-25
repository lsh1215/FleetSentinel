import { useEffect, useRef } from "react";
import maplibregl, { type Map as MlMap, type GeoJSONSource } from "maplibre-gl";
import { telemetryStore } from "../lib/telemetryStore";

/**
 * fleet 지도.
 *
 * ## 왜 DOM 마커를 쓰지 않는가
 *
 * `new maplibregl.Marker()`는 차량마다 DOM 노드를 만들고 매 프레임 `transform`을 갱신한다.
 * 4대면 괜찮지만 수백 대가 되면 레이아웃·합성 비용이 선형으로 늘어 프레임이 무너진다.
 *
 * 대신 **GeoJSON 소스 + GL 레이어** 하나에 전 차량을 담고 `setData()`로 통째 갱신한다.
 * 렌더는 GPU가 하고, 차량 수가 늘어도 드로우콜은 그대로다.
 *
 * ## 왜 React 상태를 쓰지 않는가
 *
 * 위치는 초당 수십 번 바뀐다. 이걸 state에 넣으면 지도 컴포넌트가 그 빈도로 리렌더된다.
 * 여기서는 **rAF 루프가 저장소를 직접 읽어 `setData`만 호출**한다 — React는 이 컴포넌트를
 * 마운트 이후 한 번도 다시 그리지 않는다.
 */
interface Props {
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export function FleetMap({ selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const rafRef = useRef<number>(0);
  const selectedRef = useRef(selectedId);
  const didFitRef = useRef(false);
  selectedRef.current = selectedId;

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://demotiles.maplibre.org/style.json",
      center: [103.7884, 1.2988],
      zoom: 13,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      // 데모 베이스맵을 관제 화면에 맞게 어둡게 덮는다.
      for (const layer of map.getStyle().layers ?? []) {
        if (layer.type === "background") map.setPaintProperty(layer.id, "background-color", "#0b1220");
        if (layer.type === "fill") map.setPaintProperty(layer.id, "fill-color", "#131c2e");
        if (layer.type === "line") map.setPaintProperty(layer.id, "line-color", "#1e2a42");
      }

      map.addSource("trails", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "trails",
        type: "line",
        source: "trails",
        paint: {
          "line-color": ["case", ["get", "selected"], "#5eead4", "#2f6f68"],
          "line-width": ["case", ["get", "selected"], 3, 1.5],
          "line-opacity": 0.85,
        },
      });

      map.addSource("vehicles", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "vehicle-halo",
        type: "circle",
        source: "vehicles",
        paint: {
          "circle-radius": ["case", ["get", "selected"], 16, 11],
          "circle-color": ["case", ["get", "harsh"], "#ef4444", "#38bdf8"],
          "circle-opacity": 0.18,
        },
      });
      map.addLayer({
        id: "vehicles",
        type: "circle",
        source: "vehicles",
        paint: {
          "circle-radius": ["case", ["get", "selected"], 7, 5],
          "circle-color": ["case", ["get", "harsh"], "#ef4444", "#38bdf8"],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#0b1220",
        },
      });
      map.addLayer({
        id: "vehicle-labels",
        type: "symbol",
        source: "vehicles",
        layout: {
          "text-field": ["get", "label"],
          "text-size": 11,
          "text-offset": [0, 1.4],
          "text-anchor": "top",
          "text-allow-overlap": true,
        },
        paint: { "text-color": "#cbd5e1", "text-halo-color": "#0b1220", "text-halo-width": 1.5 },
      });

      map.on("click", "vehicles", (e) => {
        const id = e.features?.[0]?.properties?.["vehicleId"];
        if (typeof id === "string") onSelect(id);
      });
      map.on("mouseenter", "vehicles", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "vehicles", () => (map.getCanvas().style.cursor = ""));
    });

    // ── rAF 갱신 루프: React 렌더를 거치지 않는다 ──────────────────────
    const tick = () => {
      rafRef.current = requestAnimationFrame(tick);
      const m = mapRef.current;
      if (!m || !m.isStyleLoaded()) return;

      const vehicles = telemetryStore.listVehicles();
      const sel = selectedRef.current;

      const points: GeoJSON.Feature[] = [];
      const lines: GeoJSON.Feature[] = [];
      for (const v of vehicles) {
        if (!v.pos) continue;
        const selected = v.vehicleId === sel;
        points.push({
          type: "Feature",
          // GeoJSON은 [lon, lat] 순서다. 내부 표기는 (lat, lon)이라 여기서 뒤집는다.
          geometry: { type: "Point", coordinates: [v.pos[1], v.pos[0]] },
          properties: {
            vehicleId: v.vehicleId,
            label: `${v.vehicleId}  ${(v.speedMps * 3.6).toFixed(0)}km/h`,
            selected,
            harsh: v.speedMps > 0 && Math.abs(v.yawRate) > 0.35,
          },
        });
        if (v.trail.length > 1) {
          lines.push({
            type: "Feature",
            geometry: { type: "LineString", coordinates: v.trail },
            properties: { selected },
          });
        }
      }

      (m.getSource("vehicles") as GeoJSONSource | undefined)?.setData({
        type: "FeatureCollection",
        features: points,
      });
      (m.getSource("trails") as GeoJSONSource | undefined)?.setData({
        type: "FeatureCollection",
        features: lines,
      });

      // 첫 위치가 들어오면 한 번만 전체 차량이 보이도록 맞춘다.
      if (!didFitRef.current && points.length > 0) {
        didFitRef.current = true;
        const b = new maplibregl.LngLatBounds();
        for (const f of points) b.extend((f.geometry as GeoJSON.Point).coordinates as [number, number]);
        m.fitBounds(b, { padding: 80, maxZoom: 15, duration: 800 });
      }
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      map.remove();
      mapRef.current = null;
    };
    // 마운트 시 1회만. selectedId는 ref로 읽으므로 의존성에 넣지 않는다 —
    // 넣으면 선택이 바뀔 때마다 지도가 통째로 재생성된다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={containerRef} className="map" />;
}
