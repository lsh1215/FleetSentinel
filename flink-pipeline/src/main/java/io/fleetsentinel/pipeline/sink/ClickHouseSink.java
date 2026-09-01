package io.fleetsentinel.pipeline.sink;

import io.fleetsentinel.pipeline.model.Decoded;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.streaming.api.checkpoint.CheckpointedFunction;
import org.apache.flink.runtime.state.FunctionInitializationContext;
import org.apache.flink.runtime.state.FunctionSnapshotContext;
import org.apache.flink.streaming.api.functions.sink.legacy.RichSinkFunction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * ClickHouse 배치 INSERT 싱크.
 *
 * <h2>⚠️ 이 싱크는 exactly-once가 아니다</h2>
 *
 * <p>ClickHouse는 체크포인트에 걸친 트랜잭션을 지원하지 않으므로 <b>2PC를 못 한다</b>.
 * 체크포인트 복구 시 마지막 체크포인트 이후에 쓴 행이 다시 쓰인다 — 즉 at-least-once다.
 *
 * <p>그 중복은 {@code ReplacingMergeTree(ingest_time)} 가 {@code ORDER BY
 * (vehicle_id, boot_id, seq)} 로 흡수한다. <b>머지 시점에</b> 지우므로 exactly-once가
 * "쓰기 시점"이 아니라 <b>"읽기 시점"에 닫힌다</b>(SDD L-14). 그래서 질의는
 * {@code FINAL} 이 박힌 뷰를 봐야 한다 — {@code infra/clickhouse/001-schema.sql}.
 *
 * <p>Flink dedup이 이걸 못 막는 이유는, 체크포인트 복구 시 <b>dedup 상태도 함께 되감기기</b>
 * 때문이다. 재생분을 "처음 보는 것"으로 통과시킨다. 두 장치가 서로 다른 구멍을 닫는다.
 *
 * <h2>배치</h2>
 *
 * <p>ClickHouse는 작은 INSERT를 매우 싫어한다(파트가 폭증해 머지가 못 따라간다). 그래서
 * 배치가 차거나 체크포인트가 올 때만 flush 한다. 체크포인트에서 flush 하는 이유는 버퍼에
 * 남은 것이 체크포인트 이후로 밀리면 그만큼 재생 구간이 커지기 때문이다.
 */
public class ClickHouseSink extends RichSinkFunction<Decoded> implements CheckpointedFunction {

    private static final long serialVersionUID = 1L;
    private static final Logger log = LoggerFactory.getLogger(ClickHouseSink.class);

    private final String url;
    private final String user;
    private final String password;
    private final int batchSize;

    private transient Connection conn;
    private transient List<Decoded> buffer;

    public ClickHouseSink(String url, String user, String password, int batchSize) {
        this.url = url;
        this.user = user;
        this.password = password;
        this.batchSize = batchSize;
    }

    @Override
    public void open(OpenContext ctx) throws Exception {
        buffer = new ArrayList<>(batchSize);
        conn = DriverManager.getConnection(url, user, password);
        conn.setAutoCommit(true);
        log.info("ClickHouse 연결: {}", url);
    }

    @Override
    public void invoke(Decoded value, Context context) throws Exception {
        buffer.add(value);
        if (buffer.size() >= batchSize) {
            flush();
        }
    }

    @Override
    public void snapshotState(FunctionSnapshotContext context) throws Exception {
        // 체크포인트 시점에 비운다. 안 비우면 버퍼 내용이 다음 체크포인트로 밀리고,
        // 그만큼 복구 시 재생 구간이 커진다.
        flush();
    }

    @Override
    public void initializeState(FunctionInitializationContext context) {
        // 상태를 들지 않는다 — 버퍼는 체크포인트마다 비워지고, 재생은 소스가 담당한다.
    }

    @Override
    public void close() throws Exception {
        try {
            flush();
        } finally {
            if (conn != null) {
                conn.close();
            }
        }
    }

    private void flush() throws SQLException {
        if (buffer.isEmpty()) {
            return;
        }
        // 테이블별로 나눠 넣는다. 한 스트림에 세 종류가 섞여 온다.
        for (Decoded.Kind kind : Decoded.Kind.values()) {
            List<Decoded> rows = buffer.stream().filter(d -> d.kind() == kind).toList();
            if (!rows.isEmpty()) {
                insert(kind, rows);
            }
        }
        buffer.clear();
    }

    private void insert(Decoded.Kind kind, List<Decoded> rows) throws SQLException {
        String sql = switch (kind) {
            case SIGNAL -> """
                    INSERT INTO fleet.signals_raw
                      (vehicle_id, boot_id, seq, scene_id, channel, sensor_time, log_time,
                       values_num, values_vec, values_str, lat, lon)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""";
            case PERCEPTION -> """
                    INSERT INTO fleet.perception_raw
                      (vehicle_id, boot_id, seq, scene_id, sample_id, sensor_time,
                       track_id, category, attribute,
                       center_x, center_y, center_z, size_w, size_l, size_h,
                       rot_w, rot_x, rot_y, rot_z,
                       visibility, num_lidar_pts, num_radar_pts, lat, lon)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""";
            case SEGMENT -> """
                    INSERT INTO fleet.segments_raw
                      (vehicle_id, boot_id, seq, segment_id, scene_id, blob_uri,
                       t_start, t_end, sensor_channels, size_bytes, checksum,
                       sample_count, state, drop_reason, calibration)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""";
        };

        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            for (Decoded d : rows) {
                int i = 1;
                ps.setString(i++, d.vehicleId());
                ps.setString(i++, d.bootId());
                ps.setLong(i++, d.seq());
                for (Object v : d.columns()) {
                    setValue(ps, i++, v);
                }
                ps.addBatch();
            }
            ps.executeBatch();
        }
    }

    private static void setValue(PreparedStatement ps, int i, Object v) throws SQLException {
        if (v == null) {
            ps.setObject(i, null);
        } else if (v instanceof Map<?, ?> || v instanceof List<?> || v instanceof Object[]) {
            ps.setObject(i, v);
        } else {
            ps.setObject(i, v);
        }
    }
}
