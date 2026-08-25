import { useEffect, useRef } from "react";
import maplibregl, { type Map as MlMap, type GeoJSONSource } from "maplibre-gl";
import { telemetryStore } from "../lib/telemetryStore";
import { boxFootprint } from "../lib/geo";

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
  /** 선택 차량을 화면 중앙에 유지한다. 끄면 자유 탐색. */
  follow: boolean;
  /** 인지 객체 발자국을 지도에 투영한다. */
  showObjects: boolean;
}

/**
 * 클래스별 색.
 *
 * 색 수를 최소로 묶는다 — nuScenes 카테고리는 23종이지만 관제에서 필요한 구분은
 * **취약 도로 사용자 / 차량 / 정적 장애물** 셋이다. 23색을 쓰면 아무것도 안 보인다.
 */
const CLASS_COLOR: Record<string, string> = {
  adult: "#e0b341",
  child: "#e0b341",
  police_officer: "#e0b341",
  construction_worker: "#e0b341",
  bicycle: "#e0b341",
  motorcycle: "#e0b341",
};
const VEHICLE_CLASSES = new Set(["car", "truck", "bus", "trailer", "construction", "emergency"]);

function classColor(cat: string): string {
  if (CLASS_COLOR[cat]) return CLASS_COLOR[cat]; // 취약 도로 사용자 — 노랑
  if (VEHICLE_CLASSES.has(cat)) return "#6f9fd8"; // 차량 — 청
  return "#6b7480"; // 그 외 정적 장애물 — 회색
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export function FleetMap({ selectedId, onSelect, follow, showObjects }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const rafRef = useRef<number>(0);
  const selectedRef = useRef(selectedId);
  const followRef = useRef(follow);
  const showObjectsRef = useRef(showObjects);
  const didFitRef = useRef(false);
  selectedRef.current = selectedId;
  followRef.current = follow;
  showObjectsRef.current = showObjects;

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      // CARTO Dark Matter 벡터 스타일. 키가 필요 없고 도로·거리명·건물이 실제로 들어 있다.
      // 이전에 쓰던 demotiles는 **데모용 저해상도 세계지도**라 줌 13 이상에서 도로가 없다 —
      // 차량이 도로 위인지 강 위인지 분간이 안 돼 관제 용도로 성립하지 않았다.
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [103.7884, 1.2988],
      zoom: 13,
      // CARTO/OSM 타일은 출처 표시가 이용 조건이다. 접었다 펼 수 있게만 한다.
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-right");
    // 축척은 관제에서 필수다 — "저 차가 얼마나 떨어져 있나"를 눈으로 재야 한다.
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }), "bottom-left");

    map.on("load", () => {
      // Dark Matter는 이미 어두운 스타일이라 재색칠이 필요 없다. 이전에는 데모 스타일을
      // 레이어 타입별로 덮어썼는데, 의미가 다른 레이어를 같은 색으로 칠하는 거친 방법이었다.

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
          // 최근 구간이 진하다 — 진행 방향이 한눈에 읽힌다.
          "line-opacity": [
            "case",
            ["all", ["get", "selected"], ["get", "recent"]], 0.95,
            ["get", "selected"], 0.3,
            ["get", "recent"], 0.5,
            0.15,
          ],
        },
      });

      // ── 인지 객체 발자국 ────────────────────────────────────────────
      // 자율주행 관제를 일반 fleet 관제와 구별하는 지점이다 — 차량이 **어디 있는지**가
      // 아니라 **무엇을 보고 있는지**를 보여준다. 3D 박스를 위에서 본 사각형으로 투영한다.
      map.addSource("objects", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "object-fill",
        type: "fill",
        source: "objects",
        // 줌 14 미만에서는 객체가 픽셀 몇 개라 의미가 없고 화면만 지저분해진다.
        minzoom: 14,
        paint: {
          "fill-color": ["get", "color"],
          // 저신뢰(LiDAR 미관측) 객체는 거의 투명하게 — 지우지는 않는다.
          // 23%가 그런 라벨이므로 숨기면 데이터를 오해하게 된다(§7.1).
          "fill-opacity": ["case", ["get", "lowConf"], 0.06, 0.2],
        },
      });
      map.addLayer({
        id: "object-outline",
        type: "line",
        source: "objects",
        minzoom: 14,
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["case", ["get", "lowConf"], 0.6, 1.2],
          // 저신뢰는 점선으로 — 색만으로 구분하면 색약에서 안 보인다.
          "line-dasharray": ["case", ["get", "lowConf"], ["literal", [2, 2]], ["literal", [1, 0]]],
          "line-opacity": ["case", ["get", "lowConf"], 0.45, 0.9],
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

      // 진행 방향 화살표. headingDeg를 계산해두고 쓰지 않고 있었다 —
      // 점만 있으면 차가 어디로 가는지 알 수 없어 관제에서 절반의 정보가 빠진다.
      map.addLayer({
        id: "vehicle-heading",
        type: "symbol",
        source: "vehicles",
        minzoom: 11,
        layout: {
          "text-field": "\u25B2",
          "text-font": ["Open Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 11, 9, 17, 15],
          // 지도 기준으로 회전시킨다. viewport 기준이면 지도를 회전할 때 방향이 어긋난다.
          "text-rotate": ["get", "heading"],
          "text-rotation-alignment": "map",
          "text-allow-overlap": true,
          "text-ignore-placement": true,
          "text-offset": [0, -1.15],
        },
        paint: {
          "text-color": [
            "case",
            ["get", "alert"], "#d94a3d",
            ["get", "selected"], "#e8eaed",
            "#8b95a5",
          ],
          "text-halo-color": "#0d0f13",
          "text-halo-width": 1,
          // 정차 중이면 흐리게 — 방향 정보가 무의미하다.
          "text-opacity": ["case", ["get", "moving"], 1, 0.25],
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

      // 인지 객체 클릭 — 무엇을 근거로 그렇게 인지했는지 보여준다.
      // 관제에서 "저 박스가 왜 저기 있나"를 물을 수 있어야 한다.
      map.on("click", "object-fill", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties ?? {};
        const lowConf = p["lowConf"] === true || p["lowConf"] === "true";
        new maplibregl.Popup({ closeButton: false, className: "obj-popup", maxWidth: "220px" })
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="op-cat">${p["category"] ?? "?"}</div>` +
              `<div class="op-row"><span>LiDAR 포인트</span><b>${p["lidarPts"] ?? "?"}</b></div>` +
              `<div class="op-row"><span>가시성</span><b>${p["visibility"] ?? "?"}</b></div>` +
              (lowConf
                ? `<div class="op-warn">LiDAR 미관측 — 저신뢰 라벨</div>`
                : ""),
          )
          .addTo(map);
      });
      map.on("mouseenter", "object-fill", () => (map.getCanvas().style.cursor = "help"));
      map.on("mouseleave", "object-fill", () => (map.getCanvas().style.cursor = ""));

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
      const boxes: GeoJSON.Feature[] = [];
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
            heading: v.headingDeg,
            moving: v.speedMps > 0.5,
            selected,
            alert: Math.abs(v.yawRate) > 0.35 || v.zeroLidarCount > 0,
          },
        });
        if (v.trail.length > 1) {
          // 궤적을 최근/과거 두 구간으로 쪼갠다. 한 줄로 그리면 어느 쪽이 최신인지,
          // 즉 차가 어디서 어디로 갔는지 읽을 수 없다.
          const cut = Math.max(1, Math.floor(v.trail.length * 0.65));
          lines.push({
            type: "Feature",
            geometry: { type: "LineString", coordinates: v.trail.slice(0, cut + 1) },
            properties: { selected, recent: false },
          });
          lines.push({
            type: "Feature",
            geometry: { type: "LineString", coordinates: v.trail.slice(cut) },
            properties: { selected, recent: true },
          });
        }

        // 인지 객체는 **선택 차량만** 그린다. 전 차량을 동시에 그리면 겹쳐서
        // 어느 차가 무엇을 보는지 알 수 없고, 그게 이 뷰의 존재 이유다.
        if (showObjectsRef.current && selected && v.location) {
          for (const o of v.objects) {
            const ring = boxFootprint(o.cx, o.cy, o.width, o.length, o.yaw, v.location);
            if (!ring) continue;
            boxes.push({
              type: "Feature",
              // LonLat은 readonly 튜플이라 GeoJSON의 가변 배열 타입과 겹치지 않는다.
              // 값은 같으므로 여기서 한 번만 복사해 넘긴다.
              geometry: { type: "Polygon", coordinates: [ring.map((p) => [p[0], p[1]])] },
              properties: {
                color: classColor(o.category),
                lowConf: o.lidarPts === 0,
                category: o.category,
                lidarPts: o.lidarPts,
                visibility: o.visibility,
              },
            });
          }
        }
      }

      (m.getSource("objects") as GeoJSONSource | undefined)?.setData({
        type: "FeatureCollection",
        features: boxes,
      });
      (m.getSource("vehicles") as GeoJSONSource | undefined)?.setData({
        type: "FeatureCollection",
        features: points,
      });
      (m.getSource("trails") as GeoJSONSource | undefined)?.setData({
        type: "FeatureCollection",
        features: lines,
      });

      // 따라가기: 선택 차량이 뷰포트 밖으로 나가려 하면 다시 중앙으로 끌어온다.
      // 매 프레임 easeTo를 부르면 사용자의 팬 조작을 계속 뺏으므로, 화면 안쪽
      // 여유 영역을 벗어났을 때만 개입한다.
      if (followRef.current && sel) {
        const v = vehicles.find((x) => x.vehicleId === sel);
        if (v?.pos) {
          const target: [number, number] = [v.pos[1], v.pos[0]];
          const pt = m.project(target);
          const { width, height } = m.getCanvas().getBoundingClientRect();
          const margin = 0.28; // 가장자리 28% 안으로 들어오면 재중심
          const outside =
            pt.x < width * margin ||
            pt.x > width * (1 - margin) ||
            pt.y < height * margin ||
            pt.y > height * (1 - margin);
          if (outside) m.easeTo({ center: target, duration: 700 });
        }
      }

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
