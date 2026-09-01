package io.fleetsentinel.pipeline;

import io.fleetsentinel.pipeline.dedup.DedupFunction;
import io.fleetsentinel.pipeline.dedup.SeqWindow;
import io.fleetsentinel.pipeline.model.Decoded;
import io.fleetsentinel.pipeline.model.DlqRecord;
import io.fleetsentinel.pipeline.model.Envelope;
import io.fleetsentinel.pipeline.sink.ClickHouseSink;
import io.fleetsentinel.pipeline.transform.DecodeFunction;
import java.time.Duration;
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
 * <pre>
 * Kafka telemetry.records ─▶ 봉투 파싱 ─▶ dedup ─▶ 디코드+검증+좌표파생 ─▶ ClickHouse
 *                                                        (kind 헤더로 계층 분기)
 *                    │                      │
 *                    └──── DLQ ─────────────┘
 * </pre>
 *
 * <h2>exactly-once의 범위</h2>
 *
 * <p>Flink는 <b>상태</b>에 대해 exactly-once다 — 체크포인트가 연산자 상태와 Kafka 오프셋을
 * 함께 스냅샷하므로 복구 시 둘이 같이 되감긴다. 그러나 <b>ClickHouse는 2PC를 못 하므로</b>
 * 싱크 구간은 at-least-once이고, {@code ReplacingMergeTree} 멱등 upsert가 흡수한다.
 * 결과적으로 exactly-once가 <b>읽기 시점에 닫힌다</b>(SDD L-14).
 *
 * <p>제출:
 * <pre>{@code
 * flink run -d target/flink-pipeline-0.1.0.jar \
 *   --bootstrap kafka1:9092 --clickhouse jdbc:ch://clickhouse:8123/fleet
 * }</pre>
 */
public final class TelemetryPipeline {

    /** 파싱조차 안 되는 것은 이 태그로 빠진다. */
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
                // earliest: 재처리 가능해야 한다는 것이 Kafka 채택 근거였다(SDD §4.1).
                .setStartingOffsets(OffsetsInitializer.earliest())
                .setDeserializer(new EnvelopeDeserializer())
                .build();

        DataStream<Envelope> raw = env.fromSource(
                source, WatermarkStrategy.noWatermarks(), "kafka");

        // dedup — 차량별 keyed state. 파티션 키와 같으므로 셔플이 없다.
        DataStream<Envelope> deduped = raw
                .keyBy(Envelope::vehicleId)
                .process(new DedupFunction(window))
                .name("dedup")
                .uid("dedup");   // uid를 고정해야 상태를 이어받으며 재배포할 수 있다

        // 디코드 + 검증 + 좌표 파생. 실패는 side output으로 DLQ에 간다.
        SingleOutputStreamOperator<Decoded> decoded = deduped
                .process(new DecodeFunction())
                .name("decode-validate-derive")
                .uid("decode");

        decoded.addSink(new ClickHouseSink(chUrl, chUser, chPassword, batchSize))
                .name("clickhouse")
                .uid("clickhouse");

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
