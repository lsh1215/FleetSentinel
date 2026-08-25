import { describe, expect, it } from "vitest";
import {
  MAP_ORIGINS,
  assertLatLon,
  bearingDeg,
  boxFootprint,
  distanceM,
  enuToWgs84,
  toLonLat,
} from "../geo";

const SEOUL = [37.5665, 126.978] as const;
const BOSTON = [42.3368, -71.0579] as const;

describe("좌표 순서 가드", () => {
  it("정상 위경도는 그대로 통과한다", () => {
    expect(assertLatLon(SEOUL, "t")).toEqual(SEOUL);
    expect(assertLatLon(BOSTON, "t")).toEqual(BOSTON);
  });

  it("lat/lon이 뒤바뀌면 잡아낸다 — 이게 가드의 존재 이유다", () => {
    // 싱가포르를 (lon, lat)으로 잘못 넘긴 경우. 경도 103은 위도가 될 수 없다.
    expect(() => assertLatLon([103.7847, 1.2882], "t")).toThrow(/순서가 뒤바뀐/);
  });

  it("경도 범위도 검사한다", () => {
    expect(() => assertLatLon([37.5, 200], "t")).toThrow(/±180/);
  });

  it("NaN·Infinity를 거른다", () => {
    expect(() => assertLatLon([Number.NaN, 126], "t")).toThrow(/유한하지 않/);
    expect(() => assertLatLon([37, Number.POSITIVE_INFINITY], "t")).toThrow(/유한하지 않/);
  });

  it("오류 메시지에 호출 지점이 담긴다", () => {
    expect(() => assertLatLon([999, 0], "ingestSignals/ego_pose")).toThrow(
      /ingestSignals\/ego_pose/,
    );
  });
});

describe("toLonLat", () => {
  it("GeoJSON 순서로 뒤집는다", () => {
    expect(toLonLat(SEOUL)).toEqual([126.978, 37.5665]);
  });
});

describe("distanceM", () => {
  it("서울–싱가포르가 실제 대권거리와 맞는다", () => {
    const km = distanceM(SEOUL, [1.2882, 103.7847]) / 1000;
    expect(km).toBeGreaterThan(4600);
    expect(km).toBeLessThan(4750);
  });

  it("같은 점은 0이다", () => {
    expect(distanceM(SEOUL, SEOUL)).toBeCloseTo(0, 6);
  });
});

describe("bearingDeg", () => {
  it("정북은 0도", () => {
    expect(bearingDeg([37.0, 127.0], [38.0, 127.0])).toBeCloseTo(0, 1);
  });

  it("동쪽으로 가면 90도에 가깝되 정확히 90은 아니다", () => {
    // 대권 항로는 극쪽으로 휜다. 같은 위도선을 따라가도 초기 방위각은 90°보다
    // 약간 작다(북반구 기준). 37°N에서 경도 1° 이동 시 약 89.7°.
    // 이걸 90으로 단언하면 구현이 아니라 테스트가 틀린다.
    const b = bearingDeg([37.0, 127.0], [37.0, 128.0]);
    expect(b).toBeGreaterThan(89);
    expect(b).toBeLessThan(90);
  });

  it("적도에서는 정확히 90도다 — 휨이 사라지는 유일한 위도", () => {
    expect(bearingDeg([0, 127.0], [0, 128.0])).toBeCloseTo(90, 6);
  });

  it("항상 [0, 360) 범위다", () => {
    const b = bearingDeg([37.0, 127.0], [36.0, 126.0]); // 남서
    expect(b).toBeGreaterThanOrEqual(0);
    expect(b).toBeLessThan(360);
    expect(b).toBeGreaterThan(180);
  });
});

describe("enuToWgs84", () => {
  it("원점(0,0)은 지도 남서쪽 모서리로 변환된다", () => {
    const p = enuToWgs84(0, 0, "boston-seaport");
    expect(p).not.toBeNull();
    expect(p![0]).toBeCloseTo(42.336849169438615, 9);
    expect(p![1]).toBeCloseTo(-71.05785369873047, 9);
  });

  it("동쪽 이동은 경도를, 북쪽 이동은 위도를 늘린다", () => {
    const o = MAP_ORIGINS["boston-seaport"]!;
    const east = enuToWgs84(1000, 0, "boston-seaport")!;
    const north = enuToWgs84(0, 1000, "boston-seaport")!;
    expect(east[1]).toBeGreaterThan(o[1]);
    expect(north[0]).toBeGreaterThan(o[0]);
  });

  it("백엔드 구현과 같은 값을 낸다 — 어긋나면 차량과 인지 객체가 다른 위치에 찍힌다", () => {
    // exploration/fleetsentinel_ingest/geo.py 로 검증한 실제 ego_pose 좌표.
    // scene-0061 첫 프레임: ENU(411.30, 1180.89) → (1.29882, 103.78845)
    const p = enuToWgs84(411.3039349319818, 1180.8903791765097, "singapore-onenorth")!;
    expect(p[0]).toBeCloseTo(1.29882, 4);
    expect(p[1]).toBeCloseTo(103.78845, 4);
  });

  it("모르는 지역은 null — 조용히 (0,0)에 찍지 않는다", () => {
    expect(enuToWgs84(100, 100, "seoul-gangnam")).toBeNull();
  });
});

describe("boxFootprint", () => {
  it("닫힌 사각형 링을 돌려준다", () => {
    const ring = boxFootprint(400, 1180, 1.9, 4.7, 0, "singapore-onenorth")!;
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual(ring[4]); // 첫 점으로 닫힘
  });

  it("길이 방향이 yaw를 따른다 — yaw=0이면 길이가 북쪽(경도 아님)으로 뻗는다", () => {
    // nuScenes 규약: 박스 로컬 x축이 길이 방향이고 ENU에서 x는 동쪽이다.
    // yaw=0이면 길이가 동쪽을 향하므로 경도 폭이 위도 폭보다 커야 한다.
    const ring = boxFootprint(400, 1180, 2, 10, 0, "singapore-onenorth")!;
    const lons = ring.map((p) => p[0]);
    const lats = ring.map((p) => p[1]);
    const lonSpanM = (Math.max(...lons) - Math.min(...lons)) * 111_320 * Math.cos((1.29 * Math.PI) / 180);
    const latSpanM = (Math.max(...lats) - Math.min(...lats)) * 110_540;
    expect(lonSpanM).toBeGreaterThan(latSpanM);
    expect(lonSpanM).toBeCloseTo(10, 0);
    expect(latSpanM).toBeCloseTo(2, 0);
  });

  it("yaw를 90도 돌리면 길이·폭 방향이 바뀐다", () => {
    const ring = boxFootprint(400, 1180, 2, 10, Math.PI / 2, "singapore-onenorth")!;
    const lons = ring.map((p) => p[0]);
    const lats = ring.map((p) => p[1]);
    const lonSpanM = (Math.max(...lons) - Math.min(...lons)) * 111_320 * Math.cos((1.29 * Math.PI) / 180);
    const latSpanM = (Math.max(...lats) - Math.min(...lats)) * 110_540;
    expect(latSpanM).toBeGreaterThan(lonSpanM);
  });

  it("모르는 지역은 null", () => {
    expect(boxFootprint(0, 0, 2, 4, 0, "nowhere")).toBeNull();
  });
});
