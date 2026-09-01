package io.fleetsentinel.pipeline.model;

import java.io.Serializable;
import java.nio.charset.StandardCharsets;
import org.apache.kafka.clients.consumer.ConsumerRecord;

/**
 * Kafka 레코드 하나. <b>페이로드는 아직 열지 않는다.</b>
 *
 * <p>신원 3튜플 {@code (vehicle_id, boot_id, seq)}은 게이트웨이가 헤더에 넣었고, 그 중
 * {@code vehicle_id}는 <b>클라이언트 인증서에서 나온 값</b>이다(SDD S-11). 페이로드 안의
 * 값을 믿지 않는다 — 두 벌이 있으면 어느 쪽을 믿느냐로 구멍이 열린다.
 */
public final class Envelope implements Serializable {

    private static final long serialVersionUID = 1L;

    private final String vehicleId;
    private final String bootId;
    private final long seq;
    private final String kind;
    private final byte[] payload;
    private final String topic;

    public Envelope(String vehicleId, String bootId, long seq, String kind,
                    byte[] payload, String topic) {
        this.vehicleId = vehicleId;
        this.bootId = bootId;
        this.seq = seq;
        this.kind = kind;
        this.payload = payload;
        this.topic = topic;
    }

    /**
     * Kafka 레코드에서 봉투를 만든다.
     *
     * @throws IllegalArgumentException 헤더가 빠졌을 때. 게이트웨이가 항상 넣으므로
     *         없다는 것은 다른 생산자가 토픽에 쓴 것이고, 조용히 통과시키면 안 된다
     */
    public static Envelope of(ConsumerRecord<byte[], byte[]> record) {
        String vehicleId = header(record, "vehicle_id");
        String bootId = header(record, "boot_id");
        String seqRaw = header(record, "seq");
        String kind = header(record, "kind");
        if (vehicleId == null || bootId == null || seqRaw == null) {
            throw new IllegalArgumentException(
                    "전송 헤더가 빠졌다: vehicle_id/boot_id/seq (topic=" + record.topic() + ")");
        }
        // 키는 게이트웨이가 인증서 신원으로 넣는다. 헤더와 어긋나면 계약 위반이다.
        if (record.key() != null) {
            String key = new String(record.key(), StandardCharsets.UTF_8);
            if (!key.equals(vehicleId)) {
                throw new IllegalArgumentException(
                        "파티션 키와 vehicle_id 헤더가 다르다: key=" + key + " header=" + vehicleId);
            }
        }
        return new Envelope(vehicleId, bootId, Long.parseLong(seqRaw), kind,
                record.value(), record.topic());
    }

    private static String header(ConsumerRecord<byte[], byte[]> r, String key) {
        var h = r.headers().lastHeader(key);
        return h == null ? null : new String(h.value(), StandardCharsets.UTF_8);
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

    public String kind() {
        return kind;
    }

    public byte[] payload() {
        return payload;
    }

    public String topic() {
        return topic;
    }

    @Override
    public String toString() {
        return "Envelope[%s/%s/%d %s %dB]".formatted(vehicleId, bootId, seq, kind,
                payload == null ? 0 : payload.length);
    }
}
