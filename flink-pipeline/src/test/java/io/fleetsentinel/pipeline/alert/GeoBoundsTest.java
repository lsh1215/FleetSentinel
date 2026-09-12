package io.fleetsentinel.pipeline.alert;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class GeoBoundsTest {

    @Test
    void parsesMultipleLocations() {
        var bounds = GeoBounds.parseAll(
                "boston=42.1,42.5,-71.3,-70.9;singapore=1.20,1.50,103.60,104.00");

        assertThat(bounds).containsOnlyKeys("boston", "singapore");
        assertThat(bounds.get("singapore").contains(1.30, 103.80)).isTrue();
        assertThat(bounds.get("singapore").contains(1.60, 103.80)).isFalse();
    }

    @Test
    void rejectsInvalidOrDuplicateBounds() {
        assertThatThrownBy(() -> GeoBounds.parseAll(" "))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> GeoBounds.parseAll("map=2,1,3,4"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> GeoBounds.parseAll("map=1,2,3,4;map=1,2,3,4"))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
