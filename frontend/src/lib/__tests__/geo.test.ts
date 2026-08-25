import { describe, expect, it } from "vitest";
import { assertLatLon, bearingDeg, distanceM, toLonLat } from "../geo";

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
