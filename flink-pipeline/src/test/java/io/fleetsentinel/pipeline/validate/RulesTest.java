package io.fleetsentinel.pipeline.validate;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.apache.avro.Schema;
import org.apache.avro.generic.GenericData;
import org.apache.avro.generic.GenericRecord;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** {@code data-design.md} §8.3 검증 규칙표를 그대로 확인한다. */
class RulesTest {

    private static Schema schema(String name) throws Exception {
        try (InputStream in = RulesTest.class.getResourceAsStream("/schemas/" + name)) {
            return new Schema.Parser().parse(
                    new String(in.readAllBytes(), StandardCharsets.UTF_8));
        }
    }

    private static GenericRecord signal(Map<String, Object> num, Map<String, Object> vec)
            throws Exception {
        var r = new GenericData.Record(schema("vehicle-signal.avsc"));
        r.put("scene_id", "s");
        r.put("channel", "test");
        r.put("sensor_time", 1L);
        r.put("log_time", 1L);
        r.put("values_num", num);
        r.put("values_vec", vec);
        r.put("values_str", Map.of());
        return r;
    }

    @Test
    @DisplayName("음수 속도는 BUSINESS_RULE_FAILURE")
    void negativeSpeed() throws Exception {
        assertThat(Rules.checkSignal(signal(Map.of("vehicle_speed", -1.0), Map.of())))
                .isPresent();
        assertThat(Rules.checkSignal(signal(Map.of("vehicle_speed", 0.0), Map.of())))
                .isEmpty();
    }

    @Test
    @DisplayName("정규화되지 않은 쿼터니언은 거절한다 — 자세가 무의미해진다")
    void unnormalizedQuaternion() throws Exception {
        assertThat(Rules.checkSignal(signal(Map.of(),
                Map.of("rotation", List.of(1.0, 1.0, 1.0, 1.0)))))     // |q| = 2
                .isPresent();
        assertThat(Rules.checkSignal(signal(Map.of(),
                Map.of("rotation", List.of(1.0, 0.0, 0.0, 0.0)))))     // |q| = 1
                .isEmpty();
    }

    @Test
    @DisplayName("실제 ego_pose 쿼터니언은 통과한다")
    void realQuaternionPasses() throws Exception {
        // scene-0061 첫 ego_pose 실측값
        assertThat(Rules.checkSignal(signal(Map.of(), Map.of("rotation",
                List.of(0.5720320396729045, -0.0016977771610471074,
                        0.011798001930183783, -0.8201446642457809)))))
                .isEmpty();
    }

    @Test
    @DisplayName("크기가 0 이하인 박스는 거절한다")
    void zeroSizeBox() throws Exception {
        var r = perception();
        r.put("size_w", 0.0);
        assertThat(Rules.checkPerception(r)).isPresent();
    }

    @Test
    @DisplayName("num_lidar_pts=0 은 버리지 않는다 — 라벨의 23.1%가 그렇다")
    void unobservedLabelIsKept() throws Exception {
        var r = perception();
        r.put("num_lidar_pts", 0);
        // 저신뢰 플래그로 분류할 뿐 DLQ로 보내지 않는다(§8.1).
        assertThat(Rules.checkPerception(r)).isEmpty();
    }

    private static GenericRecord perception() throws Exception {
        var r = new GenericData.Record(schema("perception-object.avsc"));
        r.put("scene_id", "s");
        r.put("sample_id", "k");
        r.put("sensor_time", 1L);
        r.put("track_id", "t");
        r.put("category", "vehicle.car");
        r.put("attribute", null);
        r.put("center_x", 1.0);
        r.put("center_y", 2.0);
        r.put("center_z", 3.0);
        r.put("size_w", 1.9);
        r.put("size_l", 4.7);
        r.put("size_h", 1.6);
        r.put("rot_w", 1.0);
        r.put("rot_x", 0.0);
        r.put("rot_y", 0.0);
        r.put("rot_z", 0.0);
        r.put("visibility", "v80-100");
        r.put("num_lidar_pts", 42);
        r.put("num_radar_pts", 3);
        return r;
    }
}
