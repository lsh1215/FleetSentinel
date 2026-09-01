package io.fleetsentinel.pipeline.model;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.avro.generic.GenericRecord;

/**
 * 검증·파생까지 끝난 레코드. 싱크가 이걸 그대로 INSERT 한다.
 *
 * <p>신원 3튜플은 별도 필드로, 나머지는 {@link #columns()} 순서대로 담는다 — 싱크의
 * {@code VALUES (?,?,...)} 순서와 1:1이다.
 */
public final class Decoded implements Serializable {

    private static final long serialVersionUID = 1L;

    public enum Kind { SIGNAL, PERCEPTION, SEGMENT }

    private final Kind kind;
    private final String vehicleId;
    private final String bootId;
    private final long seq;
    private final List<Object> columns;

    private Decoded(Kind kind, String vehicleId, String bootId, long seq, List<Object> columns) {
        this.kind = kind;
        this.vehicleId = vehicleId;
        this.bootId = bootId;
        this.seq = seq;
        this.columns = columns;
    }

    public Kind kind() {
        return kind;
    }

    public String vehicleId() {
        return vehicleId;
    }

    public String bootId() {
        return bootId;
    }

    public long seq() {
        return seq;
    }

    public List<Object> columns() {
        return columns;
    }

    /** ① 신호. `lat`/`lon` 은 Flink 가 파생한 값이며 실패 시 null 이다(무손실). */
    public static Decoded signal(Envelope env, GenericRecord r, Double lat, Double lon) {
        List<Object> c = new ArrayList<>();
        c.add(str(r, "scene_id"));
        c.add(str(r, "channel"));
        c.add(micros(r, "sensor_time"));
        c.add(micros(r, "log_time"));
        c.add(map(r, "values_num"));
        c.add(map(r, "values_vec"));
        c.add(map(r, "values_str"));
        c.add(lat);
        c.add(lon);
        return new Decoded(Kind.SIGNAL, env.vehicleId(), env.bootId(), env.seq(), c);
    }

    /** ② 인지 박스. 좌표가 글로벌 프레임이라 ego 지역을 알아야 파생할 수 있다. */
    public static Decoded perception(Envelope env, GenericRecord r, Double lat, Double lon) {
        List<Object> c = new ArrayList<>();
        c.add(str(r, "scene_id"));
        c.add(str(r, "sample_id"));
        c.add(micros(r, "sensor_time"));
        c.add(str(r, "track_id"));
        c.add(str(r, "category"));
        c.add(str(r, "attribute"));
        for (String f : List.of("center_x", "center_y", "center_z",
                "size_w", "size_l", "size_h",
                "rot_w", "rot_x", "rot_y", "rot_z")) {
            c.add(r.get(f));
        }
        c.add(str(r, "visibility"));
        c.add(r.get("num_lidar_pts"));
        c.add(r.get("num_radar_pts"));
        c.add(lat);
        c.add(lon);
        return new Decoded(Kind.PERCEPTION, env.vehicleId(), env.bootId(), env.seq(), c);
    }

    /** ③ 클립 참조. 파일은 오브젝트 스토리지에 있고 이건 보관증이다. */
    public static Decoded segment(Envelope env, GenericRecord r) {
        List<Object> c = new ArrayList<>();
        c.add(str(r, "segment_id"));
        c.add(str(r, "scene_id"));
        c.add(str(r, "blob_uri"));
        c.add(micros(r, "t_start"));
        c.add(micros(r, "t_end"));
        c.add(strList(r, "sensor_channels"));
        c.add(r.get("size_bytes"));
        c.add(str(r, "checksum"));
        c.add(r.get("sample_count"));
        c.add(str(r, "state"));
        c.add(str(r, "drop_reason"));
        c.add(map(r, "calibration"));
        return new Decoded(Kind.SEGMENT, env.vehicleId(), env.bootId(), env.seq(), c);
    }

    // ── Avro → JDBC 변환 ────────────────────────────────────────────────

    /** Avro 문자열은 {@code Utf8} 이라 그대로 넘기면 드라이버가 못 알아본다. */
    private static String str(GenericRecord r, String field) {
        Object v = r.get(field);
        return v == null ? null : v.toString();
    }

    /** timestamp-micros → java.sql.Timestamp. ClickHouse DateTime64(6) 에 맞춘다. */
    private static java.sql.Timestamp micros(GenericRecord r, String field) {
        Object v = r.get(field);
        if (!(v instanceof Number n)) {
            return null;
        }
        long us = n.longValue();
        var ts = new java.sql.Timestamp(us / 1000);
        ts.setNanos((int) (Math.floorMod(us, 1_000_000L) * 1000L));
        return ts;
    }

    private static Map<String, Object> map(GenericRecord r, String field) {
        Object v = r.get(field);
        if (!(v instanceof Map<?, ?> m)) {
            return Map.of();
        }
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map.Entry<?, ?> e : m.entrySet()) {
            Object val = e.getValue();
            if (val instanceof List<?> list) {
                // Array(Float64) 로 넘어갈 벡터
                List<Double> nums = new ArrayList<>(list.size());
                for (Object o : list) {
                    nums.add(o instanceof Number n ? n.doubleValue() : null);
                }
                out.put(e.getKey().toString(), nums);
            } else if (val instanceof CharSequence cs) {
                out.put(e.getKey().toString(), cs.toString());
            } else {
                out.put(e.getKey().toString(), val);
            }
        }
        return out;
    }

    private static List<String> strList(GenericRecord r, String field) {
        Object v = r.get(field);
        if (!(v instanceof List<?> list)) {
            return List.of();
        }
        List<String> out = new ArrayList<>(list.size());
        for (Object o : list) {
            out.add(o == null ? null : o.toString());
        }
        return out;
    }
}
