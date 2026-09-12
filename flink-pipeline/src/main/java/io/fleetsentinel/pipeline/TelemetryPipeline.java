package io.fleetsentinel.pipeline;

import io.fleetsentinel.pipeline.alert.AlertEvent;
import io.fleetsentinel.pipeline.alert.AlertJsonSerializationSchema;
import io.fleetsentinel.pipeline.alert.GeoBounds;
import io.fleetsentinel.pipeline.alert.OddBoundaryFunction;
import io.fleetsentinel.pipeline.alert.VehicleMonitorFunction;
import io.fleetsentinel.pipeline.dedup.DedupFunction;
import io.fleetsentinel.pipeline.dedup.SeqWindow;
import io.fleetsentinel.pipeline.model.Decoded;
import io.fleetsentinel.pipeline.model.DlqRecord;
import io.fleetsentinel.pipeline.model.Envelope;
import io.fleetsentinel.pipeline.sink.ClickHouseSink;
import io.fleetsentinel.pipeline.transform.DecodeFunction;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.util.ParameterTool;
import org.apache.flink.configuration.ExternalizedCheckpointRetention;
import org.apache.flink.connector.base.DeliveryGuarantee;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.datastream.SingleOutputStreamOperator;
import org.apache.flink.streaming.api.environment.CheckpointConfig;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.util.OutputTag;

/**
 * FleetSentinel 스트림 처리 잡.
 *
 *   Kafka telemetry.records ─▶ 봉투 파싱 ─▶ dedup ─▶ 디코드+검증+좌표파생 ─▶ ClickHouse
 *                                                          (kind 헤더로 계층 분기)
 *                      │                      │
 *                      └──── DLQ ─────────────┘
 *
 * exactly-once 는 상태까지다. 체크포인트가 연산자 상태와 Kafka 오프셋을 함께 찍으므로
 * 복구하면 둘이 같이 되감긴다. 하지만 ClickHouse 는 2PC 를 못 해서 싱크 구간은
 * at-least-once 이고, 거기서 생기는 중복은 ReplacingMergeTree 가 흡수한다.
 * 그래서 exactly-once 가 쓰기 시점이 아니라 읽기 시점에 닫힌다.
 *
 * 제출:
 *   flink run -d target/flink-pipeline-0.1.0.jar \
 *     --bootstrap kafka1:9092 --clickhouse jdbc:ch://clickhouse:8123/fleet
 */
public final class TelemetryPipeline {

    /** 곁가지 출력의 이름표. 본류와 타입이 달라 이걸로 구분한다. 불량 레코드가 여기로 빠진다. */
    public static final OutputTag<DlqRecord> DLQ =
            new OutputTag<>("dlq", org.apache.flink.api.common.typeinfo.TypeInformation.of(DlqRecord.class));

    private TelemetryPipeline() {
    }

    public static void main(String[] args) throws Exception {
        ParameterTool p = ParameterTool.fromArgs(args);

        String bootstrap = p.get("bootstrap", "localhost:29092");
        String chUrl = p.get("clickhouse", "jdbc:ch://localhost:8124/fleet");
        String chUser = p.get("clickhouse-user", "fleet");
        String chPassword = p.get("clickhouse-password", "fleet");
        String group = p.get("group", "fleetsentinel-pipeline");
        int window = p.getInt("dedup-window", SeqWindow.DEFAULT_WINDOW);
        int batchSize = p.getInt("batch-size", 1000);
        long checkpointMs = p.getLong("checkpoint-ms", 10_000);
        String alertTopic = p.get("alert-topic", "fleet.alerts");
        Map<String, GeoBounds> oddBounds = GeoBounds.parseAll(p.getRequired("odd-bounds"));
        long oddSustainedMs = p.getLong("odd-sustained-ms", 30_000);

        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();

        // 체크포인트가 exactly-once의 근거다. 오프셋과 상태가 함께 스냅샷된다.
        env.enableCheckpointing(checkpointMs);
        CheckpointConfig cp = env.getCheckpointConfig();
        cp.setMinPauseBetweenCheckpoints(checkpointMs / 2);
        cp.setCheckpointTimeout(Duration.ofMinutes(5).toMillis());
        cp.setTolerableCheckpointFailureNumber(3);
        // 잡을 취소해도 체크포인트를 남긴다 — 재배포 시 상태를 이어받으려면 필요하다.
        cp.setExternalizedCheckpointRetention(
                ExternalizedCheckpointRetention.RETAIN_ON_CANCELLATION);

        KafkaSource<Envelope> source = KafkaSource.<Envelope>builder()
                .setBootstrapServers(bootstrap)
                // **토픽 하나**다. 계층별로 나누면 `seq` 단일 수열이 조각나서
                // dedup 이 연속성을 볼 수 없다 — Kafka 는 파티션 안에서만 순서를 보장한다.
                // 계층 분기는 kind 헤더로 DecodeFunction 이 한다.
                .setTopics(p.get("topic", "telemetry.records"))
                .setGroupId(group)
                // earliest = 토픽 맨 앞부터 읽는다. 재처리가 되어야 한다는 것이
                // 애초에 Kafka 를 고른 이유였다.
                .setStartingOffsets(OffsetsInitializer.earliest())
                .setDeserializer(new EnvelopeDeserializer())
                .build();

        DataStream<Envelope> raw = env.fromSource(
                source, WatermarkStrategy.noWatermarks(), "kafka");

        // 차량별로 갈라 같은 차량은 항상 같은 태스크로 보낸다. 그래야 그 차량의
        // 비트맵 상태를 한 곳에서만 만진다. Kafka 파티션 키도 vehicle_id 라 셔플이 없다.
        // Envelope::vehicleId 는 env -> env.vehicleId() 를 짧게 쓴 것이다.
        DataStream<Envelope> deduped = raw
                .keyBy(Envelope::vehicleId)
                .process(new DedupFunction(window))
                .name("dedup")
                // uid 는 이 연산자의 고유 이름이다. 고정해 둬야 재배포할 때 Flink 가
                // 예전 체크포인트의 상태를 같은 연산자에 도로 꽂아 준다.
                .uid("dedup");

        // 디코드 + 검증 + 좌표 파생. 실패는 side output으로 DLQ에 간다.
        SingleOutputStreamOperator<Decoded> decoded = deduped
                .process(new DecodeFunction())
                .name("decode-validate-derive")
                .uid("decode");

        decoded.addSink(new ClickHouseSink(chUrl, chUser, chPassword, batchSize))
                .name("clickhouse")
                .uid("clickhouse");

        DataStream<AlertEvent> oddAlerts = decoded
                .filter(Decoded::isEgoPose)
                .name("odd-input")
                .keyBy(Decoded::vehicleId)
                .process(new OddBoundaryFunction(oddBounds, oddSustainedMs))
                .name("odd-boundary")
                .uid("odd-boundary");

        DataStream<AlertEvent> monitorAlerts = decoded
                .filter(Decoded::isVehicleMonitor)
                .keyBy(Decoded::vehicleId)
                .process(new VehicleMonitorFunction(p.getLong("stop-after-ms", 30_000),
                        p.getLong("monitor-stale-ms", 5_000)))
                .name("vehicle-monitor").uid("vehicle-monitor-v1");

        oddAlerts.union(monitorAlerts)
                .sinkTo(KafkaSink.<AlertEvent>builder()
                        .setBootstrapServers(bootstrap)
                        .setRecordSerializer(KafkaRecordSerializationSchema.<AlertEvent>builder()
                                .setTopic(alertTopic)
                                .setKeySerializationSchema(
                                        event -> event.vehicleId().getBytes(StandardCharsets.UTF_8))
                                .setValueSerializationSchema(new AlertJsonSerializationSchema())
                                .build())
                        // EXACTLY_ONCE는 checkpoint 완료까지 경보를 숨긴다. 경보는 즉시 보이고,
                        // 장애 중복은 안정적인 event_id로 소비자가 제거하는 편이 맞다.
                        .setDeliveryGuarantee(DeliveryGuarantee.AT_LEAST_ONCE)
                        .build())
                .name("alerts-kafka")
                .uid("alerts-kafka");

        // DLQ. 원본 바이트를 무손실로 보존한다.
        decoded.getSideOutput(DLQ)
                .map(d -> "%s|%s|%s|%s".formatted(
                        d.errorClass(), d.pipelineStep(), d.sourceSubscription(), d.errorDetail()))
                .sinkTo(KafkaSink.<String>builder()
                        .setBootstrapServers(bootstrap)
                        .setRecordSerializer(KafkaRecordSerializationSchema.builder()
                                .setTopic("telemetry.dlq")
                                .setValueSerializationSchema(new SimpleStringSchema())
                                .build())
                        // DLQ는 at-least-once로 충분하다 — 중복 격리는 유실보다 낫다.
                        .setDeliveryGuarantee(DeliveryGuarantee.AT_LEAST_ONCE)
                        .build())
                .name("dlq")
                .uid("dlq");

        env.execute("fleetsentinel-telemetry");
    }
}
