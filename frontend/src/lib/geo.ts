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
