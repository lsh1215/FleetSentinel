import { describe, expect, it } from "vitest";
import { TelemetryStore, type AlertEvent } from "../telemetryStore";

describe("Flink alert 전이", () => {
  it("서로 다른 이상을 독립적으로 유지하고 수신 재개만으로 센서 오류를 지우지 않는다", () => {
    const store = new TelemetryStore();
    store.ingestAlert(alert("fault", "SENSOR_FAULT"));
    store.ingestAlert(alert("stale", "TELEMETRY_STALE"));
    store.ingestAlert(alert("recovered", "TELEMETRY_RECOVERED"));
    expect([...store.getVehicle("AV-0001")!.activeAlerts]).toEqual(["sensor"]);
    store.ingestAlert(alert("healthy", "SENSOR_RECOVERED"));
    expect(store.getVehicle("AV-0001")!.activeAlerts.size).toBe(0);
    expect(store.listEvents()).toHaveLength(4);
  });
  it("ODD 이탈과 복귀가 차량의 현재 경보 상태를 열고 닫는다", () => {
    const store = new TelemetryStore();
    store.ingestAlert(alert("exit-1", "ODD_EXITED"));

    expect(store.getVehicle("AV-0001")?.activeAlerts.has("odd")).toBe(true);
    expect(store.listEvents().map((event) => event.kind)).toEqual(["odd_exit"]);

    store.ingestAlert(alert("return-1", "ODD_RETURNED"));

    expect(store.getVehicle("AV-0001")?.activeAlerts.has("odd")).toBe(false);
    expect(store.listEvents().map((event) => event.kind)).toEqual(["odd_return", "odd_exit"]);
  });

  it("at-least-once로 같은 eventId가 다시 와도 피드에는 한 번만 넣는다", () => {
    const store = new TelemetryStore();
    const event = alert("exit-1", "ODD_EXITED");

    store.ingestAlert(event);
    store.ingestAlert(event);

    expect(store.listEvents()).toHaveLength(1);
    expect(store.getVehicle("AV-0001")?.activeAlerts.has("odd")).toBe(true);
  });

  it("복귀 뒤 늦게 재전송된 이탈 이벤트가 경보 상태를 다시 열지 않는다", () => {
    const store = new TelemetryStore();
    const exit = alert("exit-1", "ODD_EXITED");
    store.ingestAlert(exit);
    store.ingestAlert(alert("return-1", "ODD_RETURNED"));

    store.ingestAlert(exit);

    expect(store.getVehicle("AV-0001")?.activeAlerts.has("odd")).toBe(false);
    expect(store.listEvents()).toHaveLength(2);
  });
});

function alert(eventId: string, type: AlertEvent["type"]): AlertEvent {
  return {
    eventId,
    type,
    severity: type.endsWith("RETURNED") ? "INFO" : "WARNING",
    vehicleId: "AV-0001",
    eventTimeMs: 1_000,
    detectedAtMs: 1_100,
    message: "test alert",
  };
}
