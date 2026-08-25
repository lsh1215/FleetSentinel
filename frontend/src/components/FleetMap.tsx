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
        if (layer.type === "background") map.setPaintProperty(layer.id, "background-color", "#0d0f13");
        if (layer.type === "fill") map.setPaintProperty(layer.id, "fill-color", "#15181e");
        if (layer.type === "line") map.setPaintProperty(layer.id, "line-color", "#1f242c");
      }

      map.addSource("trails", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "trails",
        type: "line",
        source: "trails",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["case", ["get", "selected"], "#e8eaed", "#5a6473"],
          // 줌에 따라 굵기를 보간한다. 고정 굵기면 줌아웃 시 화면이 선으로 덮인다.
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            10, ["case", ["get", "selected"], 1.5, 0.6],
            16, ["case", ["get", "selected"], 3, 1.4],
          ],
          "line-opacity": ["case", ["get", "selected"], 0.9, 0.35],
        },
      });

      map.addSource("vehicles", { type: "geojson", data: EMPTY });

      // 경보 상태만 후광을 준다. 평상시엔 장식을 넣지 않는다.
      map.addLayer({
        id: "vehicle-alert",
        type: "circle",
        source: "vehicles",
        filter: ["get", "alert"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 8, 16, 18],
          "circle-color": "#d94a3d",
          "circle-opacity": 0.22,
        },
      });

      map.addLayer({
        id: "vehicles",
        type: "circle",
        source: "vehicles",
        paint: {
          // 줌아웃하면 점이 작아져 뭉침이 덜 보인다.
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            9, ["case", ["get", "selected"], 4, 2.5],
            13, ["case", ["get", "selected"], 6, 4],
            17, ["case", ["get", "selected"], 8, 5.5],
          ],
          "circle-color": [
            "case",
            ["get", "alert"], "#d94a3d",
            ["get", "selected"], "#e8eaed",
            "#8b95a5",
          ],
          "circle-stroke-width": ["case", ["get", "selected"], 2, 1],
          "circle-stroke-color": "#0d0f13",
        },
      });

      map.addLayer({
        id: "vehicle-labels",
        type: "symbol",
        source: "vehicles",
        // 줌 12 미만에서는 라벨을 아예 그리지 않는다 — 그 아래는 차량이 뭉쳐
        // 라벨이 정보를 주지 않고 화면만 가린다.
        minzoom: 12,
        layout: {
          "text-field": ["get", "label"],
          "text-font": ["Open Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 12, 9, 17, 11],
          "text-offset": [0, 1.1],
          "text-anchor": "top",
          // ⚠️ 핵심 수정. true로 두면 MapLibre의 충돌 회피가 꺼져 라벨이 그대로 쌓인다.
          "text-allow-overlap": false,
          // 자리가 없으면 라벨만 생략하고 점은 남긴다(점까지 사라지면 차량을 놓친다).
          "text-optional": true,
          "text-padding": 3,
          // 선택 차량이 우선 배치되도록 정렬 키를 준다(작을수록 우선).
          "symbol-sort-key": ["case", ["get", "selected"], 0, ["get", "alert"], 1, 2],
        },
        paint: {
          "text-color": ["case", ["get", "selected"], "#e8eaed", "#8b95a5"],
          "text-halo-color": "#0d0f13",
          "text-halo-width": 1.4,
        },
      });

      // 선택 차량은 줌과 무관하게 항상 라벨을 보여준다 — 지금 보고 있는 대상이라서.
      map.addLayer({
        id: "vehicle-label-selected",
        type: "symbol",
        source: "vehicles",
        filter: ["get", "selected"],
        layout: {
          "text-field": ["get", "label"],
          "text-font": ["Open Sans Regular"],
          "text-size": 11,
          "text-offset": [0, 1.1],
          "text-anchor": "top",
          "text-allow-overlap": true,
          "text-padding": 3,
        },
        paint: {
          "text-color": "#e8eaed",
          "text-halo-color": "#0d0f13",
          "text-halo-width": 1.6,
        },
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
            label: v.vehicleId,
            selected,
            alert: Math.abs(v.yawRate) > 0.35 || v.zeroLidarCount > 0,
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
