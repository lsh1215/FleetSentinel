package io.fleetsentinel.pipeline;

import io.fleetsentinel.pipeline.model.Envelope;
import org.apache.flink.api.common.typeinfo.TypeInformation;
import org.apache.flink.connector.kafka.source.reader.deserializer.KafkaRecordDeserializationSchema;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.flink.util.Collector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Kafka 레코드를 Envelope 으로 감싼다. 페이로드는 아직 열지 않는다.
 *
 * 헤더가 없으면 게이트웨이가 쓴 레코드가 아니다. 그냥 통과시키면 신원 없는 레코드가
 * 파이프라인을 흐르므로 버리고 로그만 남긴다 — 이 단계에는 아직 DLQ 경로가 없다.
 * 곁가지 출력은 ProcessFunction 에서만 되기 때문이다.
 */
public class EnvelopeDeserializer implements KafkaRecordDeserializationSchema<Envelope> {

    private static final long serialVersionUID = 1L;
    private static final Logger log = LoggerFactory.getLogger(EnvelopeDeserializer.class);

    @Override
    public void deserialize(ConsumerRecord<byte[], byte[]> record, Collector<Envelope> out) {
        try {
            out.collect(Envelope.of(record));
        } catch (IllegalArgumentException e) {
            log.warn("봉투를 만들 수 없다 — 게이트웨이가 쓴 레코드가 아니다: topic={} offset={} ({})",
                    record.topic(), record.offset(), e.getMessage());
        }
    }

    @Override
    public TypeInformation<Envelope> getProducedType() {
        return TypeInformation.of(Envelope.class);
    }
}
