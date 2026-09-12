package io.fleetsentinel.pipeline.validate;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.apache.avro.generic.GenericRecord;

/**
 * 레코드가 물리적으로 말이 되는지 본다.
 *
 * 버리는 것과 태그하는 것을 구분한다. 물리적으로 불가능한 값(음수 속도, 정규화 안 된
 * 쿼터니언, 크기 0인 박스)은 DLQ로 격리한다. 반면 단조성 위반과 LiDAR 포인트가 없는
 * 주석은 버리지 않는다. 지연 도착과 관측 메타데이터는 데이터의 성질이지 오류가 아니다.
 */
public final class Rules {

    /** 쿼터니언 정규화 허용 오차. float32 왕복과 라벨 정밀도를 감안한 값이다. */
    public static final double QUAT_TOLERANCE = 1e-3;

    private Rules() {
    }

    /** @return 위반 사유. 비어 있으면 통과 */
    public static Optional<String> checkSignal(GenericRecord rec) {
        Object numsRaw = rec.get("values_num");

        // values_num 이 Map 이면 nums 로 받고, 아니면 이 블록을 건너뛴다.
        if (numsRaw instanceof Map<?, ?> nums) {
            Double speed = asDouble(nums.get(key(nums, "vehicle_speed")));
            // speed 는 없을 수 있다. null 검사가 먼저다.
            if (speed != null && speed < 0) {
                return Optional.of("vehicle_speed < 0: " + speed);
            }
        }

        Object vecsRaw = rec.get("values_vec");
        if (vecsRaw instanceof Map<?, ?> vecs) {
            // 쿼터니언은 |q| ≈ 1 이어야 한다. 아니면 자세가 무의미하다.
            // 채널마다 이름이 달라 셋 다 훑는다.
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

    /** 객체 메타데이터의 3D 박스를 검증한다. */
    public static Optional<String> checkPerception(GenericRecord rec) {
        for (String f : List.of("size_w", "size_l", "size_h")) {
            Object v = rec.get(f);
            Double d = asDouble(v);
            // !(d > 0) 은 d <= 0 과 다르다. NaN 은 어떤 비교도 false 라 이렇게 써야 걸린다.
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
        // num_lidar_pts = 0 은 거리나 가림 때문에 정상적으로 발생할 수 있다.
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
        // sha256 을 hex 로 쓰면 32바이트 × 2 = 64자다.
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
        // List 가 아니면 빠져나가고, 맞으면 list 로 받아 아래에서 쓴다.
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
     * Avro 맵의 키는 String 이 아니라 Utf8 이라, map.get("vehicle_speed") 로는 못 찾는다.
     * 키를 문자열로 바꿔 비교하고 실제 키 객체를 돌려준다.
     */
    private static Object key(Map<?, ?> map, String name) {
        for (Object k : map.keySet()) {
            if (name.equals(k.toString())) {
                return k;
            }
        }
        return name;
    }

    /** Number 면 double 로, 아니면 null. Avro 가 Integer·Long·Double 을 섞어 주기 때문이다. */
    private static Double asDouble(Object o) {
        return o instanceof Number n ? n.doubleValue() : null;
    }

    private static Long asLong(Object o) {
        return o instanceof Number n ? n.longValue() : null;
    }
}
