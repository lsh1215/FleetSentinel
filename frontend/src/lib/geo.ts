/**
 * 좌표 순서 가드.
 *
 * 이 도메인에서 가장 흔한 버그가 lat/lon 뒤바뀜이다. GeoJSON·MapLibre는 `[lon, lat]`을
 * 쓰고, 사람이 읽는 표기와 대부분의 DB 함수는 `(lat, lon)`이다. 순서를 틀리면 에러 없이
 * **엉뚱한 대륙에 점이 찍힌다** — 조용히 틀리는 종류의 버그다.
 *
 * 그래서 경계를 넘는 지점에 이름 붙은 변환을 두고, 값 범위로 즉시 잡는다.
 * (위도는 ±90을 넘을 수 없으므로, |lat| > 90이면 순서가 뒤바뀐 것이다.)
 */
export type LatLon = readonly [lat: number, lon: number];
export type LonLat = readonly [lon: number, lat: number];

export function assertLatLon(p: LatLon, where: string): LatLon {
  const [lat, lon] = p;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    throw new Error(`[${where}] 좌표가 유한하지 않다: ${lat}, ${lon}`);
  }
  if (Math.abs(lat) > 90) {
    throw new Error(
      `[${where}] 위도 ${lat}는 ±90을 벗어난다 — lat/lon 순서가 뒤바뀐 것으로 보인다`,
    );
  }
  if (Math.abs(lon) > 180) throw new Error(`[${where}] 경도 ${lon}가 ±180을 벗어난다`);
  return p;
}

/** 내부 표기(lat, lon) → GeoJSON/MapLibre 표기(lon, lat). */
export function toLonLat(p: LatLon): LonLat {
  return [p[1], p[0]];
}

/** 두 위경도 사이 거리(m) — haversine. */
export function distanceM(a: LatLon, b: LatLon): number {
  const R = 6378137;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b[0] - a[0]);
  const dLon = rad(b[1] - a[1]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** 진행 방위각(도) — 이전 위치에서 현재 위치로. 지도 아이콘 회전에 쓴다. */
export function bearingDeg(from: LatLon, to: LatLon): number {
  const rad = (d: number) => (d * Math.PI) / 180;
  const y = Math.sin(rad(to[1] - from[1])) * Math.cos(rad(to[0]));
  const x =
    Math.cos(rad(from[0])) * Math.sin(rad(to[0])) -
    Math.sin(rad(from[0])) * Math.cos(rad(to[0])) * Math.cos(rad(to[1] - from[1]));
  return (((Math.atan2(y, x) * 180) / Math.PI) + 360) % 360;
}


// ─────────────────────────────────────────────────────────────────────────
// ENU 로컬 미터 ↔ WGS84
//
// 인지 3D 박스는 **글로벌 ENU 미터 좌표**로 온다(ego_pose와 같은 프레임). 지도에 얹으려면
// 위경도로 바꿔야 하는데, 그러려면 각 지도의 원점이 필요하다.
//
// 원점은 nuscenes-devkit `map_expansion/map_api.py`가 문서화한 **남서쪽 모서리** 값이다.
// 백엔드(exploration/fleetsentinel_ingest/geo.py)와 **같은 상수·같은 방법**을 쓴다 —
// 어긋나면 차량과 인지 객체가 서로 다른 위치에 찍힌다.
//
// ⚠️ 커뮤니티에 떠도는 "보스턴 1.35배 스케일링"은 Web Mercator 축척계수(1/cos(lat))이며,
//    아래처럼 대권 방식으로 직접 변환하면 어떤 보정도 필요 없다.
// ─────────────────────────────────────────────────────────────────────────

/** 각 지도의 남서쪽 모서리 원점 [lat, lon]. */
export const MAP_ORIGINS: Record<string, LatLon> = {
  "boston-seaport": [42.336849169438615, -71.05785369873047],
  "singapore-onenorth": [1.2882100868743724, 103.78475189208984],
  "singapore-hollandvillage": [1.2993652317780957, 103.78217697143555],
  "singapore-queenstown": [1.2782562240223188, 103.76741409301758],
};

const EARTH_RADIUS_M = 6378137;

/**
 * ENU 로컬 미터 → WGS84. 원점에서의 방위각·거리로 목적지를 구하는 대권 방식이다.
 * 지원하지 않는 지역이면 null을 돌려준다 — 조용히 (0,0)에 찍는 것보다 안 그리는 편이 낫다.
 */
export function enuToWgs84(x: number, y: number, location: string): LatLon | null {
  const origin = MAP_ORIGINS[location];
  if (!origin) return null;

  const latRad = (origin[0] * Math.PI) / 180;
  const lonRad = (origin[1] * Math.PI) / 180;
  const bearing = Math.atan2(x, y);
  const angular = Math.hypot(x, y) / EARTH_RADIUS_M;

  const lat = Math.asin(
    Math.sin(latRad) * Math.cos(angular) + Math.cos(latRad) * Math.sin(angular) * Math.cos(bearing),
  );
  const lon =
    lonRad +
    Math.atan2(
      Math.sin(bearing) * Math.sin(angular) * Math.cos(latRad),
      Math.cos(angular) - Math.sin(latRad) * Math.sin(lat),
    );
  return [(lat * 180) / Math.PI, (lon * 180) / Math.PI];
}

/**
 * 3D 박스의 **평면 발자국(footprint)** 네 모서리를 GeoJSON 순서로 돌려준다.
 *
 * 중심만 변환해 오프셋을 더하면 위도에 따라 경도 스케일이 달라져 박스가 찌그러진다.
 * 그래서 **ENU 평면에서 네 모서리를 먼저 만들고 각각 변환**한다.
 *
 * nuScenes 규약: size = (width, length, height), 박스 로컬 x축이 길이 방향이고
 * yaw는 그 x축의 방위다.
 */
export function boxFootprint(
  cx: number,
  cy: number,
  width: number,
  length: number,
  yaw: number,
  location: string,
): LonLat[] | null {
  const hl = length / 2;
  const hw = width / 2;
  const cos = Math.cos(yaw);
  const sin = Math.sin(yaw);

  // 로컬 (앞뒤=길이, 좌우=폭) → 글로벌 ENU
  const local: [number, number][] = [
    [hl, hw],
    [hl, -hw],
    [-hl, -hw],
    [-hl, hw],
  ];

  const ring: LonLat[] = [];
  for (const [lx, ly] of local) {
    const gx = cx + lx * cos - ly * sin;
    const gy = cy + lx * sin + ly * cos;
    const p = enuToWgs84(gx, gy, location);
    if (!p) return null;
    ring.push([p[1], p[0]]); // GeoJSON은 [lon, lat]
  }
  ring.push(ring[0]!); // 폴리곤은 첫 점으로 닫아야 한다
  return ring;
}
