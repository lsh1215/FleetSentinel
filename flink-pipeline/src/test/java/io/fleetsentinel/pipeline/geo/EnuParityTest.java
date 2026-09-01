package io.fleetsentinel.pipeline.geo;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Python {@code geo.py}와 Java {@code Enu}가 같은 좌표를 내는지 확인한다.
 *
 * <p>이 변환이 틀리면 지도가 <b>조용히</b> 엉뚱한 곳을 가리킨다 — 예외도 안 나고 값도
 * 그럴듯해서 눈으로는 못 잡는다. 그래서 Python 결과를 픽스처로 굳혀 대조한다.
 */
class EnuParityTest {

    /** 1e-9도 ≈ 0.1 mm. 부동소수 연산 순서 차이만 허용한다. */
    private static final double TOL_DEG = 1e-9;

    @Test
    @DisplayName("무작위 624건에서 Python과 위경도가 일치한다")
    void matchesPython() throws Exception {
        List<double[]> cases = new ArrayList<>();
        List<String> locs = new ArrayList<>();
        parse(read("/geo_cross.json"), locs, cases);
        assertThat(cases).isNotEmpty();

        double worstLat = 0;
        double worstLon = 0;
        for (int i = 0; i < cases.size(); i++) {
            double[] c = cases.get(i);      // x, y, lat, lon
            double[] got = Enu.toWgs84(c[0], c[1], locs.get(i));
            worstLat = Math.max(worstLat, Math.abs(got[0] - c[2]));
            worstLon = Math.max(worstLon, Math.abs(got[1] - c[3]));
        }
        assertThat(worstLat).as("위도 최대 편차(deg)").isLessThan(TOL_DEG);
        assertThat(worstLon).as("경도 최대 편차(deg)").isLessThan(TOL_DEG);
    }

    @Test
    @DisplayName("왕복 변환이 밀리미터 안에서 닫힌다")
    void roundTrip() {
        // Python 계약({@code test_geo.py})과 같은 점·같은 임계값을 쓴다.
        for (String loc : List.of("boston-seaport", "singapore-onenorth",
                "singapore-queenstown", "singapore-hollandvillage")) {
            for (double[] p : new double[][]{{0, 0}, {500, 1200}, {1935.3, 870.2}, {-30, 42.5}}) {
                double[] ll = Enu.toWgs84(p[0], p[1], loc);
                double[] back = Enu.toEnu(ll[0], ll[1], loc);
                assertThat(Math.hypot(back[0] - p[0], back[1] - p[1]))
                        .as("%s (%.1f, %.1f) 왕복 오차(m)", loc, p[0], p[1])
                        .isLessThan(1e-3);      // 1 mm — Python 계약과 동일
            }
        }
    }

    @Test
    @DisplayName("원점 바로 옆에서 역변환 정밀도가 떨어진다 — 알려진 성질이다")
    void inverseLosesPrecisionNearOrigin() {
        // wgs84_to_enu 는 acos 를 쓰는데, 원점 1 m 옆이면 인자가 1에 극히 가까워
        // 파국적 상쇄가 일어난다. Python 구현도 같은 성질을 갖는다(같은 식이므로).
        //
        // **파이프라인은 정방향만 쓴다** — 역변환은 왕복 검증 전용이다. 그래서 이걸
        // 고치지 않고 성질로 기록한다. 숨기면 나중에 "왜 mm 오차가 나지"로 돌아온다.
        double[] ll = Enu.toWgs84(0, -1, "singapore-queenstown");
        double[] back = Enu.toEnu(ll[0], ll[1], "singapore-queenstown");
        double err = Math.hypot(back[0] - 0, back[1] - (-1));

        assertThat(err).as("원점 근처 왕복 오차(m)").isGreaterThan(1e-4);  // 실제로 나쁘다
        assertThat(err).as("그래도 센티미터 안이다").isLessThan(1e-2);
    }

    @Test
    @DisplayName("원점은 정확히 원점 좌표로 간다")
    void originMapsToOrigin() {
        double[] ll = Enu.toWgs84(0, 0, "boston-seaport");
        assertThat(ll[0]).isEqualTo(42.336849169438615, org.assertj.core.data.Offset.offset(1e-12));
        assertThat(ll[1]).isEqualTo(-71.05785369873047, org.assertj.core.data.Offset.offset(1e-12));
    }

    @Test
    @DisplayName("모르는 지역은 추측하지 않고 거절한다")
    void rejectsUnknownLocation() {
        // 원점이 틀리면 좌표가 조용히 엉뚱한 곳을 가리킨다. 예외가 낫다.
        assertThatThrownBy(() -> Enu.toWgs84(0, 0, "seoul-gangnam"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("알 수 없는 지역");
    }

    // ── 최소 JSON 파싱 ───────────────────────────────────────────────────

    private static String read(String r) throws Exception {
        try (InputStream in = EnuParityTest.class.getResourceAsStream(r)) {
            if (in == null) throw new IllegalStateException("픽스처 없음: " + r);
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static void parse(String json, List<String> locs, List<double[]> out) {
        Matcher m = Pattern.compile(
                "\\{\"loc\":\\s*\"([^\"]+)\",\\s*\"x\":\\s*(-?[\\d.eE+-]+),\\s*"
                        + "\"y\":\\s*(-?[\\d.eE+-]+),\\s*\"lat\":\\s*(-?[\\d.eE+-]+),\\s*"
                        + "\"lon\":\\s*(-?[\\d.eE+-]+)}").matcher(json);
        while (m.find()) {
            locs.add(m.group(1));
            out.add(new double[]{
                    Double.parseDouble(m.group(2)), Double.parseDouble(m.group(3)),
                    Double.parseDouble(m.group(4)), Double.parseDouble(m.group(5))});
        }
    }
}
