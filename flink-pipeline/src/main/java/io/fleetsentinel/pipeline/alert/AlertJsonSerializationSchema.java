package io.fleetsentinel.pipeline.alert;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import org.apache.flink.api.common.serialization.SerializationSchema;

/** alert 토픽의 JSON 계약. API 서버가 같은 필드 이름으로 읽는다. */
public class AlertJsonSerializationSchema implements SerializationSchema<AlertEvent> {

    private static final long serialVersionUID = 1L;
    private transient ObjectMapper mapper;

    @Override
    public void open(InitializationContext context) {
        mapper = new ObjectMapper();
    }

    @Override
    public byte[] serialize(AlertEvent element) {
        try {
            return mapper.writeValueAsBytes(element);
        } catch (IOException e) {
            throw new IllegalStateException("alert JSON 직렬화 실패", e);
        }
    }
}
