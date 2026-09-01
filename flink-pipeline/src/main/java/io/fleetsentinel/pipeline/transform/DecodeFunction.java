package io.fleetsentinel.pipeline.transform;

import io.fleetsentinel.pipeline.TelemetryPipeline;
import io.fleetsentinel.pipeline.geo.Enu;
import io.fleetsentinel.pipeline.model.Decoded;
import io.fleetsentinel.pipeline.model.DlqRecord;
import io.fleetsentinel.pipeline.model.DlqRecord.ErrorClass;
import io.fleetsentinel.pipeline.model.Envelope;
import io.fleetsentinel.pipeline.source.AvroDecoder;
import io.fleetsentinel.pipeline.validate.Rules;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.apache.avro.generic.GenericRecord;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.metrics.Counter;
import org.apache.flink.streaming.api.functions.ProcessFunction;
import org.apache.flink.util.Collector;

/**
 * Avro 디코드 → 검증 → 좌표 파생.
 *
 * <p>세 단계를 한 연산자에 둔 이유는 <b>실패 분류가 단계마다 다르기</b> 때문이다.
 * 나누면 각 연산자가 자기 DLQ 경로를 갖게 되고 그게 더 복잡하다.
 *
 * <table>
 *   <tr><td>디코드 실패</td><td>{@code PARSE_FAILURE}</td></tr>
 *   <tr><td>필드 누락</td><td>{@code SCHEMA_VALIDATION_FAILURE}</td></tr>
 *   <tr><td>물리적으로 불가능한 값</td><td>{@code BUSINESS_RULE_FAILURE}</td></tr>
 * </table>
 *
 * <p><b>좌표 변환 실패는 DLQ가 아니다.</b> `lat`/`lon`을 null로 두고 행은 살린다 —
 * 원본 ENU는 그대로 있으므로 유실이 아니고, 버리면 무손실 원칙을 어긴다.
 */
public class DecodeFunction extends ProcessFunction<Envelope, Decoded> {

    private static final long serialVersionUID = 1L;

    private transient AvroDecoder signal;
    private transient AvroDecoder perception;
    private transient AvroDecoder segment;
    private transient Counter parseFailed;
    private transient Counter ruleFailed;
    private transient Counter geoFailed;

    @Override
    public void open(OpenContext ctx) {
        signal = AvroDecoder.fromResource("/schemas/vehicle-signal.avsc");
        perception = AvroDecoder.fromResource("/schemas/perception-object.avsc");
        segment = AvroDecoder.fromResource("/schemas/segment-ref.avsc");

        var g = getRuntimeContext().getMetricGroup().addGroup("decode");
        parseFailed = g.counter("parse_failed");
        ruleFailed = g.counter("rule_failed");
        // 좌표 변환 실패는 DLQ가 아니라 지표로만 남는다. 행은 살아 있다.
        geoFailed = g.counter("geo_failed");
    }

    @Override
    public void processElement(Envelope env, Context ctx, Collector<Decoded> out) {
        // 토픽이 아니라 **kind 헤더**로 분기한다. 토픽은 하나다(TelemetryPipeline 참조).
        String kind = env.kind();
        if (kind == null) {
            dlq(ctx, env, ErrorClass.SCHEMA_VALIDATION_FAILURE, "route", "kind 헤더가 없다");
            return;
        }
        switch (kind) {
            case "RECORD_KIND_SIGNAL" -> handleSignal(env, ctx, out);
            case "RECORD_KIND_PERCEPTION" -> handlePerception(env, ctx, out);
            case "RECORD_KIND_SEGMENT_REF" -> handleSegment(env, ctx, out);
            default -> dlq(ctx, env, ErrorClass.SCHEMA_VALIDATION_FAILURE, "route",
                    "알 수 없는 kind: " + kind);
        }
    }

    private void handleSignal(Envelope env, Context ctx, Collector<Decoded> out) {
        GenericRecord r = decode(signal, env, ctx);
        if (r == null) {
            return;
        }
        Optional<String> bad = Rules.checkSignal(r);
        if (bad.isPresent()) {
            ruleFailed.inc();
            dlq(ctx, env, ErrorClass.BUSINESS_RULE_FAILURE, "validate-signal", bad.get());
            return;
        }

        // ego_pose 채널만 좌표를 갖는다. 나머지는 lat/lon 이 null 이다.
        Double lat = null;
        Double lon = null;
        double[] ll = deriveFromEgoPose(r);
        if (ll != null) {
            lat = ll[0];
            lon = ll[1];
        }
        out.collect(Decoded.signal(env, r, lat, lon));
    }

    /**
     * `ego_pose` 채널의 `translation` + `location` 으로 위경도를 만든다.
     *
     * @return 실패하면 null. <b>행은 버리지 않는다</b> — ENU 원본이 남아 있으므로
     *         나중에 다시 파생할 수 있고, 버리면 유실이다
     */
    private double[] deriveFromEgoPose(GenericRecord r) {
        Object ch = r.get("channel");
        if (ch == null || !"ego_pose".equals(ch.toString())) {
            return null;
        }
        try {
            Object vecs = r.get("values_vec");
            Object strs = r.get("values_str");
            if (!(vecs instanceof Map<?, ?> vm) || !(strs instanceof Map<?, ?> sm)) {
                return null;
            }
            List<?> t = (List<?>) lookup(vm, "translation");
            Object loc = lookup(sm, "location");
            if (t == null || t.size() < 2 || loc == null) {
                return null;
            }
            double x = ((Number) t.get(0)).doubleValue();
            double y = ((Number) t.get(1)).doubleValue();
            return Enu.toWgs84(x, y, loc.toString());
        } catch (RuntimeException e) {
            geoFailed.inc();
            return null;
        }
    }

    private void handlePerception(Envelope env, Context ctx, Collector<Decoded> out) {
        GenericRecord r = decode(perception, env, ctx);
        if (r == null) {
            return;
        }
        Optional<String> bad = Rules.checkPerception(r);
        if (bad.isPresent()) {
            ruleFailed.inc();
            dlq(ctx, env, ErrorClass.BUSINESS_RULE_FAILURE, "validate-perception", bad.get());
            return;
        }
        // 박스 좌표는 글로벌 프레임이지만 지역(location)이 레코드에 없다.
        // 신호 스트림과 조인해야 파생할 수 있어 여기서는 null 로 둔다 — 미해결.
        out.collect(Decoded.perception(env, r, null, null));
    }

    private void handleSegment(Envelope env, Context ctx, Collector<Decoded> out) {
        GenericRecord r = decode(segment, env, ctx);
        if (r == null) {
            return;
        }
        Optional<String> bad = Rules.checkSegment(r);
        if (bad.isPresent()) {
            ruleFailed.inc();
            dlq(ctx, env, ErrorClass.BUSINESS_RULE_FAILURE, "validate-segment", bad.get());
            return;
        }
        out.collect(Decoded.segment(env, r));
    }

    private GenericRecord decode(AvroDecoder dec, Envelope env, Context ctx) {
        try {
            return dec.decode(env.payload());
        } catch (Exception e) {
            parseFailed.inc();
            dlq(ctx, env, ErrorClass.PARSE_FAILURE, "decode", e.toString());
            return null;
        }
    }

    private void dlq(Context ctx, Envelope env, ErrorClass cls, String step, String detail) {
        ctx.output(TelemetryPipeline.DLQ, DlqRecord.of(env, cls, step, detail));
    }

    /** Avro 맵 키는 {@code Utf8} 이라 문자열로 직접 조회하면 안 맞는다. */
    private static Object lookup(Map<?, ?> map, String name) {
        for (Map.Entry<?, ?> e : map.entrySet()) {
            if (name.equals(e.getKey().toString())) {
                return e.getValue();
            }
        }
        return null;
    }
}
