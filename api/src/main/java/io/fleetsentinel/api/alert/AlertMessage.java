package io.fleetsentinel.api.alert;

/** Flink가 {@code fleet.alerts}에 쓰는 JSON 계약. */
public record AlertMessage(
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
        String message) {

    public AlertMessage {
        if (eventId == null || type == null || severity == null
                || vehicleId == null || message == null
                || eventId.isBlank() || vehicleId.isBlank() || message.isBlank()) {
            throw new IllegalArgumentException("alert 필수 문자열이 비어 있다");
        }
        if (sourceSeq < 0 || eventTimeMs <= 0 || detectedAtMs <= 0) {
            throw new IllegalArgumentException("alert seq 또는 시각이 잘못됐다");
        }
        if (type.name().startsWith("ODD_") && (location == null || latitude == null || longitude == null)) {
            throw new IllegalArgumentException("ODD alert 위치가 없다");
        }
    }

    public enum Type {
        ODD_EXITED,
        ODD_SUSTAINED,
        ODD_RETURNED,
        UNPLANNED_STOP, STOP_CLEARED,
        SENSOR_FAULT, SENSOR_RECOVERED,
        TELEMETRY_STALE, TELEMETRY_RECOVERED
    }

    public enum Severity { INFO, WARNING, CRITICAL }
}
