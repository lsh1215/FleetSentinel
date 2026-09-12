package io.fleetsentinel.api.alert;

import static org.assertj.core.api.Assertions.assertThat;

import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class KafkaAlertConsumerTest {

    private final AlertHub hub = new AlertHub(10);
    private final KafkaAlertConsumer consumer = new KafkaAlertConsumer(new ObjectMapper(), hub);

    @Test
    void parsesFlinkContract() {
        String value = """
                {"eventId":"vehicle-1:ODD_EXITED:boot-1:7","type":"ODD_EXITED",
                "severity":"WARNING","vehicleId":"vehicle-1","bootId":"boot-1",
                "sourceSeq":7,"eventTimeMs":1000,"detectedAtMs":1100,
                "location":"test-map","latitude":1.2,"longitude":3.4,
                "message":"차량이 ODD 경계를 벗어났다"}
                """;

        consumer.consume(new ConsumerRecord<>("fleet.alerts", 0, 3, "vehicle-1", value));

        assertThat(hub.recent(null)).singleElement().satisfies(alert -> {
            assertThat(alert.eventId()).isEqualTo("vehicle-1:ODD_EXITED:boot-1:7");
            assertThat(alert.type()).isEqualTo(AlertMessage.Type.ODD_EXITED);
        });
    }

    @Test void acceptsSensorAlertWithoutInventingCoordinates() {
        String value = """
                {"eventId":"sensor-1","type":"SENSOR_FAULT","severity":"CRITICAL",
                "vehicleId":"vehicle-1","bootId":"boot-1","sourceSeq":7,
                "eventTimeMs":1000,"detectedAtMs":1100,"message":"센서 오류 보고"}
                """;
        consumer.consume(new ConsumerRecord<>("fleet.alerts", 0, 6, "vehicle-1", value));
        assertThat(hub.recent(null)).singleElement().satisfies(alert -> {
            assertThat(alert.type()).isEqualTo(AlertMessage.Type.SENSOR_FAULT);
            assertThat(alert.latitude()).isNull();
        });
    }

    @Test
    void skipsMalformedAlertInsteadOfBlockingThePartition() {
        consumer.consume(new ConsumerRecord<>("fleet.alerts", 0, 4, "vehicle-1", "not-json"));

        assertThat(hub.recent(null)).isEmpty();
    }

    @Test
    void skipsOddAlertWithoutPosition() {
        String value = """
                {"eventId":"bad-odd","type":"ODD_EXITED","severity":"WARNING",
                "vehicleId":"vehicle-1","bootId":"boot-1","sourceSeq":7,
                "eventTimeMs":1000,"detectedAtMs":1100,"message":"ODD 이탈"}
                """;

        consumer.consume(new ConsumerRecord<>("fleet.alerts", 0, 5, "vehicle-1", value));

        assertThat(hub.recent(null)).isEmpty();
    }
}
