package io.fleetsentinel.pipeline.alert;

import java.io.Serializable;

/** Flink가 판정하고 Kafka로 내보내는 경보 계약. */
public record AlertEvent(
        String eventId,
        Type type,
        Severity severity,
        String vehicleId,
        String bootId,
        long sourceSeq,
        long eventTimeMs,
        long detectedAtMs,
        String location,
        Double latitude,
        Double longitude,
        String message) implements Serializable {

    public enum Type {
        ODD_EXITED,
        ODD_SUSTAINED,
        ODD_RETURNED,
        UNPLANNED_STOP,
        STOP_CLEARED,
        SENSOR_FAULT,
        SENSOR_RECOVERED,
        TELEMETRY_STALE,
        TELEMETRY_RECOVERED
    }

    public enum Severity { INFO, WARNING, CRITICAL }

    public static AlertEvent odd(
            Type type,
            Severity severity,
            DecodedPosition position,
            long detectedAtMs,
            String transitionId,
            String message) {
        return new AlertEvent(
                "%s:%s:%s".formatted(position.vehicleId(), type, transitionId),
                type,
                severity,
                position.vehicleId(),
                position.bootId(),
                position.seq(),
                position.eventTimeMs(),
                detectedAtMs,
                position.location(),
                position.latitude(),
                position.longitude(),
                message);
    }

    public record DecodedPosition(
            String vehicleId,
            String bootId,
            long seq,
            long eventTimeMs,
            String location,
            double latitude,
            double longitude) implements Serializable {
    }
}
