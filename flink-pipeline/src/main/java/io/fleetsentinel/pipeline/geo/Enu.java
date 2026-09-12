package io.fleetsentinel.pipeline.geo;

import java.util.Map;

/**
 * ENU 로컬 미터 ↔ WGS84 위경도. 차량 쪽 geo.py 를 옮긴 것이다.
 *
 * ego_pose.translation 은 위경도가 아니라 지역 지도 기준 ENU(동-북-상) 로컬 미터이고
 * z 는 항상 0이다. 지도에 찍으려면 변환해야 한다.
 *
 * 커뮤니티에 도는 "보스턴은 1.35배" 보정은 Web Mercator 축척계수 1/cos(위도)였다.
 * 보스턴이 42.34°라 1.3528, 싱가포르는 적도 근처라 사실상 1이다. 아래처럼 대권으로 직접
 * 변환하면 그런 보정 상수가 아예 필요 없다.
 */
public final class Enu {

    /** WGS84 장반경. */
    public static final double EARTH_RADIUS_M = 6378137.0;

    /** 지도 원점. nuscenes-devkit 의 공식 값이며 각 지도의 남서쪽 모서리다. */
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
     * ENU → WGS84. 원점에서 어느 방향으로 얼마나 갔는지로 목적지를 구하는 표준식이다.
     * 접평면 근사와 달리 원점에서 멀어져도 정확하다.
     *
     * @param x 동쪽 거리(m) — translation[0]
     * @param y 북쪽 거리(m) — translation[1]
     * @return [위도, 경도] degrees
     * @throws IllegalArgumentException 모르는 지역. 추측해서 변환하지 않는다 —
     *         원점이 틀리면 좌표가 조용히 엉뚱한 곳을 가리킨다
     */
    public static double[] toWgs84(double x, double y, String location) {
        double[] origin = ORIGINS.get(location);
        if (origin == null) {
            throw new IllegalArgumentException("알 수 없는 지역: " + location);
        }
        double latRad = Math.toRadians(origin[0]);
        double lonRad = Math.toRadians(origin[1]);

        double bearing = Math.atan2(x, y);              // 북쪽 기준 방위각
        double angular = Math.hypot(x, y) / EARTH_RADIUS_M;   // 지구 중심에서 본 각도

        double targetLat = Math.asin(
                Math.sin(latRad) * Math.cos(angular)
                        + Math.cos(latRad) * Math.sin(angular) * Math.cos(bearing));
        double targetLon = lonRad + Math.atan2(
                Math.sin(bearing) * Math.sin(angular) * Math.cos(latRad),
                Math.cos(angular) - Math.sin(latRad) * Math.sin(targetLat));

        return new double[]{Math.toDegrees(targetLat), Math.toDegrees(targetLon)};
    }

    /** WGS84 → ENU. toWgs84 의 역변환이며 왕복 오차 검증에 쓴다. */
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
