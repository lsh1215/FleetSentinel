package io.fleetsentinel.pipeline.source;

import java.io.IOException;
import java.io.InputStream;
import java.io.Serializable;
import java.nio.charset.StandardCharsets;
import org.apache.avro.Schema;
import org.apache.avro.generic.GenericDatumReader;
import org.apache.avro.generic.GenericRecord;
import org.apache.avro.io.BinaryDecoder;
import org.apache.avro.io.DecoderFactory;

/**
 * `schemas/*.avsc` 로 페이로드를 읽는다.
 *
 * <p><b>코드 생성을 쓰지 않는다.</b> 스키마는 `data-design.md` §5의 계약이고 이 잡은 그걸
 * 소비만 한다. 생성 코드를 두면 스키마가 바뀔 때마다 재생성이 필요하고, 계약의 정본이
 * 어디인지 흐려진다.
 *
 * <p>스키마 문자열을 필드로 들고 있는 이유 — {@link Schema}는 직렬화되지 않는데 Flink가
 * 함수 객체를 태스크로 보내야 하기 때문이다. 문자열로 보내고 태스크에서 파싱한다.
 */
public final class AvroDecoder implements Serializable {

    private static final long serialVersionUID = 1L;

    private final String schemaJson;
    private transient Schema schema;
    private transient GenericDatumReader<GenericRecord> reader;
    private transient BinaryDecoder decoder;

    public AvroDecoder(String schemaJson) {
        this.schemaJson = schemaJson;
    }

    /** 클래스패스의 스키마를 읽어 디코더를 만든다. */
    public static AvroDecoder fromResource(String name) {
        try (InputStream in = AvroDecoder.class.getResourceAsStream(name)) {
            if (in == null) {
                throw new IllegalStateException("스키마가 클래스패스에 없다: " + name);
            }
            return new AvroDecoder(new String(in.readAllBytes(), StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new IllegalStateException("스키마를 읽지 못했다: " + name, e);
        }
    }

    /**
     * @throws IOException 바이트가 스키마에 맞지 않을 때. 호출부가 PARSE_FAILURE 로 격리한다
     */
    public GenericRecord decode(byte[] payload) throws IOException {
        if (reader == null) {
            schema = new Schema.Parser().parse(schemaJson);
            reader = new GenericDatumReader<>(schema);
        }
        decoder = DecoderFactory.get().binaryDecoder(payload, decoder);
        return reader.read(null, decoder);
    }

    public Schema schema() {
        if (schema == null) {
            schema = new Schema.Parser().parse(schemaJson);
        }
        return schema;
    }
}
