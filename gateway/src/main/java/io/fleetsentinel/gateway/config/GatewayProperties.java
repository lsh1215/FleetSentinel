package io.fleetsentinel.gateway.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** 게이트웨이 고유 설정. gRPC 서버·TLS는 {@code spring.grpc.*}가 담당한다. */
@ConfigurationProperties(prefix = "fleetsentinel.gateway")
public class GatewayProperties {

    private final Topics topics = new Topics();
    private final Ack ack = new Ack();

    /**
     * ack 없이 받아들일 수 있는 최대 미완료 레코드 수. 넘으면 스트림을 끊는다.
     *
     * <p>차량 쪽에도 같은 이름의 상한이 있지만(WalShipper.max_inflight), 그건 차량이 지키기로
     * 한 약속이지 게이트웨이가 강제한 값이 아니다. 지키지 않는 클라이언트가 힙을 밀어버릴 수
     * 있으므로 서버가 자기 한도를 따로 갖는다.
     */
    private int maxInflight = 4096;

    public Topics getTopics() {
        return topics;
    }

    public Ack getAck() {
        return ack;
    }

    public int getMaxInflight() {
        return maxInflight;
    }

    public void setMaxInflight(int maxInflight) {
        this.maxInflight = maxInflight;
    }

    public static class Topics {
        /**
         * 계층 셋이 한 토픽으로 간다. 나누면 `seq` 단일 수열이 조각나
         * dedup 이 연속성을 볼 수 없다(RecordPublisher.topicFor 참조).
         */
        private String records = "telemetry.records";
        private String dlq = "telemetry.dlq";

        public String getRecords() {
            return records;
        }

        public void setRecords(String records) {
            this.records = records;
        }

        public String getDlq() {
            return dlq;
        }

        public void setDlq(String dlq) {
            this.dlq = dlq;
        }
    }

    public static class Ack {
        /** 이만큼 전진하면 CACK을 방출한다. */
        private int everyN = 128;

        /** 전진량이 적어도 이 시간이 지나면 방출한다. 저부하에서 커밋이 멈추지 않게 한다. */
        private Duration every = Duration.ofMillis(200);

        public int getEveryN() {
            return everyN;
        }

        public void setEveryN(int everyN) {
            this.everyN = everyN;
        }

        public Duration getEvery() {
            return every;
        }

        public void setEvery(Duration every) {
            this.every = every;
        }
    }
}
