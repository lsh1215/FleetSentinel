package io.fleetsentinel.api.alert;

import static org.assertj.core.api.Assertions.assertThat;

import io.fleetsentinel.api.alert.AlertMessage.Severity;
import io.fleetsentinel.api.alert.AlertMessage.Type;
import org.junit.jupiter.api.Test;

class AlertHubTest {

    @Test
    void deduplicatesAtLeastOnceDeliveryAndBoundsReplay() {
        var hub = new AlertHub(2);
        hub.publish(alert("event-1", "vehicle-1"));
        hub.publish(alert("event-1", "vehicle-1"));
        hub.publish(alert("event-2", "vehicle-2"));
        hub.publish(alert("event-3", "vehicle-1"));

        assertThat(hub.recent(null)).extracting(AlertMessage::eventId)
                .containsExactly("event-2", "event-3");
        assertThat(hub.recent("vehicle-1")).extracting(AlertMessage::eventId)
                .containsExactly("event-3");
    }

    private static AlertMessage alert(String eventId, String vehicleId) {
        return new AlertMessage(eventId, Type.ODD_EXITED, Severity.WARNING,
                vehicleId, "boot-1", 1, 1_000, 1_100,
                "test-map", 1.0, 2.0, "ODD 이탈");
    }
}
