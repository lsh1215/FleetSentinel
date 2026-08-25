import { useSyncExternalStore } from "react";
import { telemetryStore } from "../lib/telemetryStore";

/**
 * 차량 목록.
 *
 * 저빈도 구독자다 — `useSyncExternalStore`로 저장소의 **버전 번호**를 구독한다.
 * 스냅샷이 숫자라서 참조 동일성 문제가 없고, 저장소가 4Hz로 스로틀해 알리므로
 * 데이터 도착률(40Hz)과 무관하게 초당 4번만 리렌더된다.
 */
export function VehicleList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  useSyncExternalStore(telemetryStore.subscribe, telemetryStore.getSnapshot);
  const vehicles = telemetryStore.listVehicles();

  return (
    <div className="panel vehicle-panel">
      <div className="panel-head">
        <h2>차량</h2>
        <span className="muted">{vehicles.length}대</span>
      </div>
      <ul className="vehicle-list">
        {vehicles.map((v) => (
          <li key={v.vehicleId}>
            <button
              className={v.vehicleId === selectedId ? "vehicle sel" : "vehicle"}
              onClick={() => onSelect(v.vehicleId)}
            >
              <span className="dot" />
              <span className="vid">{v.vehicleId}</span>
              <span className="vspeed">{(v.speedMps * 3.6).toFixed(0)}<i>km/h</i></span>
              <span className="vobj">{v.objectCount}<i>obj</i></span>
              <span className="vloc">{v.location.replace("singapore-", "sg-").replace("boston-", "bos-")}</span>
            </button>
          </li>
        ))}
        {vehicles.length === 0 && <li className="empty">스트림 대기 중…</li>}
      </ul>
    </div>
  );
}
