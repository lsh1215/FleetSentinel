package io.fleetsentinel.gateway.config;

import java.util.Map;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.ByteArraySerializer;
import org.springframework.boot.kafka.autoconfigure.KafkaProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.ProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;

/**
 * 프로듀서를 명시적으로 정의한다. Boot가 자동 구성하는 {@code KafkaTemplate<?, ?>}는
 * {@code KafkaTemplate<byte[], byte[]>}로 주입되지 않는다.
 *
 * <p>여기서 강제하는 세 설정이 유실 방지 계약의 전부다. 하나라도 약해지면 CACK이
 * 거짓말을 하게 된다 — ack은 "Kafka에 안전하게 들어갔다"는 뜻이어야 한다.
 */
@Configuration(proxyBeanMethods = false)
public class KafkaProducerConfig {

    @Bean
    public ProducerFactory<byte[], byte[]> gatewayProducerFactory(KafkaProperties properties) {
        Map<String, Object> config = properties.buildProducerProperties();

        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, ByteArraySerializer.class);
        config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, ByteArraySerializer.class);

        // ① 모든 in-sync replica가 썼을 때만 성공이다. 이것보다 약하면 ack이 유실을 덮는다.
        config.put(ProducerConfig.ACKS_CONFIG, "all");

        // ② 재시도로 인한 중복을 브로커가 시퀀스 번호로 걸러낸다. 그리고 이게 켜져 있어야
        //    max.in.flight > 1에서도 파티션 내 순서가 유지된다 — CACK이 콜백 순서에
        //    기대므로(A-L5) 순서를 잃으면 "연속 최고 seq"의 의미가 달라진다.
        config.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, true);
        config.put(ProducerConfig.MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION, 5);

        return new DefaultKafkaProducerFactory<>(config);
    }

    @Bean
    public KafkaTemplate<byte[], byte[]> gatewayKafkaTemplate(ProducerFactory<byte[], byte[]> factory) {
        return new KafkaTemplate<>(factory);
    }
}
