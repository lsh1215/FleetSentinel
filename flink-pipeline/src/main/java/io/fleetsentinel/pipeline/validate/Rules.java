package io.fleetsentinel.pipeline.validate;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.apache.avro.generic.GenericRecord;

/**
 * 검증 규칙. {@code docs/data-design.md} §8.3의 표를 코드로 옮긴 것이다.
 *
 * <h2>버리는 것과 태그하는 것을 구분한다</h2>
 *
 * <p>물리적으로 불가능한 값(음수 속도, 정규화 안 된 쿼터니언, 크기 0인 박스)은 DLQ로
 * 격리한다. 반면 <b>단조성 위반과 저신뢰 라벨은 버리지 않는다</b> — 지연 도착과 미관측은
 * 데이터의 성질이지 오류가 아니고, 버리면 유실이 된다(무손실 원칙).
 */
public final class Rules {

    /** 쿼터니언 정규화 허용 오차. float32 왕복과 라벨 정밀도를 감안한 값이다. */
    public static final double QUAT_TOLERANCE = 1e-3;

    private Rules() {
    }

    /**
     * 신호 레코드를 검증한다.
     *
     * @return 위반 사유. 비어 있으면 통과
     */
    public static Optional<String> checkSignal(GenericRecord rec) {
        Object numsRaw = rec.get("values_num");
        if (numsRaw instanceof Map<?, ?> nums) {
            // 속도는 음수일 수 없다.
            Double speed = asDouble(nums.get(key(nums, "vehicle_speed")));
            if (speed != null && speed < 0) {
                return Optional.of("vehicle_speed < 0: " + speed);
            }
        }

        Object vecsRaw = rec.get("values_vec");
        if (vecsRaw instanceof Map<?, ?> vecs) {
            // 쿼터니언은 |q| ≈ 1 이어야 한다. 아니면 자세가 무의미하다.
            for (String k : List.of("rotation", "q", "orientation")) {
                Object v = vecs.get(key(vecs, k));
                Optional<String> bad = checkQuaternion(k, v);
                if (bad.isPresent()) {
                    return bad;
                }
            }
        }
        return Optional.empty();
    }

    /** 인지 박스를 검증한다. */
    public static Optional<String> checkPerception(GenericRecord rec) {
        for (String f : List.of("size_w", "size_l", "size_h")) {
            Object v = rec.get(f);
            Double d = asDouble(v);
            if (d == null || !(d > 0)) {
                return Optional.of(f + " <= 0: " + v);
            }
        }
        double w = asDouble(rec.get("rot_w"));
        double x = asDouble(rec.get("rot_x"));
        double y = asDouble(rec.get("rot_y"));
        double z = asDouble(rec.get("rot_z"));
        double norm = Math.sqrt(w * w + x * x + y * y + z * z);
        if (Math.abs(norm - 1.0) > QUAT_TOLERANCE) {
            return Optional.of("박스 쿼터니언 |q|=%.6f".formatted(norm));
        }
        // num_lidar_pts = 0 은 **버리지 않는다** — 라벨의 23.1%가 그렇고,
        // 저신뢰 플래그로 분류해 별도 취급하는 것이 큐레이션 1급 축이다(§8.1).
        return Optional.empty();
    }

    /** 세그먼트 참조를 검증한다. */
    public static Optional<String> checkSegment(GenericRecord rec) {
        Object size = rec.get("size_bytes");
        Long s = asLong(size);
        if (s == null || s <= 0) {
            return Optional.of("size_bytes <= 0: " + size);
        }
        Object count = rec.get("sample_count");
        Long c = asLong(count);
        if (c == null || c <= 0) {
            return Optional.of("sample_count <= 0: " + count);
        }
        Object checksum = rec.get("checksum");
        if (checksum == null || checksum.toString().length() != 64) {
            return Optional.of("checksum이 sha256 hex 64자가 아니다");
        }
        Object tStart = rec.get("t_start");
        Object tEnd = rec.get("t_end");
        Long a = asLong(tStart);
        Long b = asLong(tEnd);
        if (a == null || b == null || b < a) {
            return Optional.of("t_start/t_end 범위가 잘못됐다");
        }
        return Optional.empty();
    }

    private static Optional<String> checkQuaternion(String name, Object value) {
        if (!(value instanceof List<?> list) || list.size() != 4) {
            return Optional.empty();      // 없거나 길이가 다르면 이 규칙의 대상이 아니다
        }
        double sum = 0;
        for (Object o : list) {
            Double d = asDouble(o);
            if (d == null) {
                return Optional.of(name + "에 숫자가 아닌 값");
            }
            sum += d * d;
        }
        double norm = Math.sqrt(sum);
        if (Math.abs(norm - 1.0) > QUAT_TOLERANCE) {
            return Optional.of("%s 쿼터니언 |q|=%.6f".formatted(name, norm));
        }
        return Optional.empty();
    }

    /**
     * Avro 맵의 키는 {@code Utf8}이라 {@code String}으로 조회하면 안 맞는다.
     * 키를 문자열로 비교해 실제 키 객체를 찾는다.
     */
    private static Object key(Map<?, ?> map, String name) {
        for (Object k : map.keySet()) {
            if (name.equals(k.toString())) {
                return k;
            }
        }
        return name;
    }

    private static Double asDouble(Object o) {
        return o instanceof Number n ? n.doubleValue() : null;
    }

    private static Long asLong(Object o) {
        return o instanceof Number n ? n.longValue() : null;
    }
}
