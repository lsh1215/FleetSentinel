package io.fleetsentinel.pipeline.alert;

import java.io.Serializable;
import java.util.LinkedHashMap;
import java.util.Map;

/** 지역별 ODD 경계. 직사각형으로 시작하고 실제 운영에서는 폴리곤으로 교체할 수 있다. */
public record GeoBounds(double minLatitude, double maxLatitude,
                        double minLongitude, double maxLongitude) implements Serializable {

    public GeoBounds {
        if (minLatitude >= maxLatitude || minLongitude >= maxLongitude) {
            throw new IllegalArgumentException("ODD 경계의 최솟값은 최댓값보다 작아야 한다");
        }
        if (minLatitude < -90 || maxLatitude > 90
                || minLongitude < -180 || maxLongitude > 180) {
            throw new IllegalArgumentException("ODD 경계가 위경도 범위를 벗어났다");
        }
    }

    public boolean contains(double latitude, double longitude) {
        return latitude >= minLatitude && latitude <= maxLatitude
                && longitude >= minLongitude && longitude <= maxLongitude;
    }

    /** location=minLat,maxLat,minLon,maxLon;location=... 형식을 읽는다. */
    public static Map<String, GeoBounds> parseAll(String spec) {
        if (spec == null || spec.isBlank()) {
            throw new IllegalArgumentException("--odd-bounds가 필요하다");
        }
        Map<String, GeoBounds> result = new LinkedHashMap<>();
        for (String item : spec.split(";")) {
            String[] named = item.trim().split("=", 2);
            if (named.length != 2 || named[0].isBlank()) {
                throw new IllegalArgumentException("잘못된 ODD 경계: " + item);
            }
            String[] raw = named[1].split(",");
            if (raw.length != 4) {
                throw new IllegalArgumentException("ODD 경계는 숫자 4개여야 한다: " + item);
            }
            GeoBounds bounds = new GeoBounds(
                    Double.parseDouble(raw[0].trim()),
                    Double.parseDouble(raw[1].trim()),
                    Double.parseDouble(raw[2].trim()),
                    Double.parseDouble(raw[3].trim()));
            if (result.put(named[0].trim(), bounds) != null) {
                throw new IllegalArgumentException("ODD 지역이 중복됐다: " + named[0].trim());
            }
        }
        return Map.copyOf(result);
    }
}
