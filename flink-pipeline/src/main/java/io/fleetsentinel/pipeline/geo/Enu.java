package io.fleetsentinel.pipeline.geo;

import java.util.Map;

/**
 * ENU 로컬 미터 ↔ WGS84 위경도.
 *
 * <p>{@code exploration/fleetsentinel_ingest/geo.py}를 옮긴 것이다. 계약이 pytest 30건으로
 * 고정돼 있고, 좌표 체인 종단 검증(박스 안 LiDAR 포인트 대조, 오차 0)이 이 변환에 의존한다.
 *
 * <h2>왜 필요한가</h2>
 *
 * <p>{@code ego_pose.translation}은 <b>위경도가 아니다.</b> 지역 지도의 ENU(East-North-Up)
 * 로컬 미터이고 z는 항상 0이다. 지도에 찍으려면 변환해야 한다.
 *
 * <h2>"보스턴 1.35배"의 정체</h2>
 *
 * <p>커뮤니티에 떠도는 그 보정은 Web Mercator 축척계수 {@code 1/cos(lat)}였다. 보스턴이
 * 42.34°라 1.3528이고 싱가포르는 적도 근처라 1.0003(사실상 1)이다. <b>대권 방식으로 직접
 * 변환하면 어떤 보정 상수도 필요 없다</b> — 이 클래스가 그 방식이다.
 */
public final class Enu {

    /** WGS84 장반경. */
    public static final double EARTH_RADIUS_M = 6378137.0;

    /**
     * 지도 원점. {@code nuscenes-devkit}의 {@code map_expansion/map_api.py} 공식 값이며
     * 각 지도의 남서쪽 모서리다.
     */
    private static final Map<String, double[]> ORIGINS = Map.of(
            "boston-seaport", new double[]{42.336849169438615, -71.05785369873047},
            "singapore-onenorth", new double[]{1.2882100868743724, 103.78475189208984},
            "singapore-hollandvillage", new double[]{1.2993652317780957, 103.78217697143555},
            "singapore-queenstown", new double[]{1.2782562240223188, 103.76741409301758});

    private Enu() {
    }

    public static boolean known(String location) {
        return ORIGINS.containsKey(location);
    }

    /**
     * ENU → WGS84 (대권 방식).
     *
     * <p>원점에서의 방위각과 거리로 목적지를 구하는 표준식이다. 이동에 따른 경도 수렴 변화를
     * 반영하므로 접평면 근사보다 원점에서 멀 때 정확하다.
     *
     * @param x 동쪽 거리(m) — {@code translation[0]}
     * @param y 북쪽 거리(m) — {@code translation[1]}
     * @return {@code [위도, 경도]} degrees
     * @throws IllegalArgumentException 모르는 지역. <b>추측해서 변환하지 않는다</b> —
     *         원점이 틀리면 좌표가 조용히 엉뚱한 곳을 가리킨다
     */
    public static double[] toWgs84(double x, double y, String location) {
        double[] origin = ORIGINS.get(location);
        if (origin == null) {
            throw new IllegalArgumentException("알 수 없는 지역: " + location);
        }
        double latRad = Math.toRadians(origin[0]);
        double lonRad = Math.toRadians(origin[1]);

        double bearing = Math.atan2(x, y);
        double angular = Math.hypot(x, y) / EARTH_RADIUS_M;

        double targetLat = Math.asin(
                Math.sin(latRad) * Math.cos(angular)
                        + Math.cos(latRad) * Math.sin(angular) * Math.cos(bearing));
        double targetLon = lonRad + Math.atan2(
                Math.sin(bearing) * Math.sin(angular) * Math.cos(latRad),
                Math.cos(angular) - Math.sin(latRad) * Math.sin(targetLat));

        return new double[]{Math.toDegrees(targetLat), Math.toDegrees(targetLon)};
    }

    /** WGS84 → ENU. {@link #toWgs84}의 역변환이며 왕복 오차 검증에 쓴다. */
    public static double[] toEnu(double lat, double lon, String location) {
        double[] origin = ORIGINS.get(location);
        if (origin == null) {
            throw new IllegalArgumentException("알 수 없는 지역: " + location);
        }
        double latRad = Math.toRadians(lat);
        double lonRad = Math.toRadians(lon);
        double refLat = Math.toRadians(origin[0]);
        double refLon = Math.toRadians(origin[1]);

        double dLon = lonRad - refLon;
        double cos = Math.sin(refLat) * Math.sin(latRad)
                + Math.cos(refLat) * Math.cos(latRad) * Math.cos(dLon);
        double angular = Math.acos(Math.max(-1.0, Math.min(1.0, cos)));
        double bearing = Math.atan2(
                Math.sin(dLon) * Math.cos(latRad),
                Math.cos(refLat) * Math.sin(latRad)
                        - Math.sin(refLat) * Math.cos(latRad) * Math.cos(dLon));

        double dist = angular * EARTH_RADIUS_M;
        return new double[]{dist * Math.sin(bearing), dist * Math.cos(bearing)};
    }
}
