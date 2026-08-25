import { useEffect, useState } from "react";
import { telemetryStore } from "../lib/telemetryStore";

/**
 * 헤더 KPI 스트립.
 *
 * 실무 관제 툴은 **핵심 수치를 항상 보이게** 둔다. 패널을 뒤져야 알 수 있는 값이면
 * 사고가 났을 때 못 본다. 여기 있는 다섯 개는 "지금 시스템이 정상인가"를 판단하는
 * 최소 집합이다.
 *
 * 1초 주기로 읽는다. 저장소가 자체 계측한 값을 그대로 표시하므로 계산 비용이 없다.
 */
interface Health {
  kafka_consumer_lag: number;
  dlq_count: number;
  brokers_in_sync: number;
}

export function KpiStrip() {
  const [tp, setTp] = useState({ rec: 0, batch: 0 });
  const [vehicles, setVehicles] = useState(0);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    const readLocal = () => {
      setTp({ rec: telemetryStore.recordsPerSec, batch: telemetryStore.batchesPerSec });
      setVehicles(telemetryStore.listVehicles().filter((v) => v.pos !== null).length);
    };
    const poll = () =>
      fetch("/api/health", { signal: ctrl.signal })
        .then((r) => r.json())
        .then(setHealth)
        .catch(() => {});
    readLocal();
    poll();
    const a = setInterval(readLocal, 1000);
    const b = setInterval(poll, 2000);
    return () => {
      ctrl.abort();
      clearInterval(a);
      clearInterval(b);
    };
  }, []);

  const dlq = health?.dlq_count ?? 0;
  const isr = health?.brokers_in_sync ?? 0;

  return (
    <div className="kpi">
      <Item k="active" v={String(vehicles)} unit="veh" />
      <Item k="ingest" v={tp.rec.toLocaleString()} unit="rec/s" />
      <Item k="batch" v={String(tp.batch)} unit="/s" />
      <Item k="lag" v={health ? String(health.kafka_consumer_lag) : "—"} unit="" />
      <Item k="dlq" v={String(dlq)} unit="" state={dlq > 0 ? "alarm" : undefined} />
      <Item k="isr" v={health ? `${isr}/3` : "—"} unit="" state={health && isr < 3 ? "warn" : undefined} />
    </div>
  );
}

function Item({
  k,
  v,
  unit,
  state,
}: {
  k: string;
  v: string;
  unit: string;
  state?: "alarm" | "warn";
}) {
  return (
    <div className={state ? `kpi-i ${state}` : "kpi-i"}>
      <span className="kpi-k">{k}</span>
      <span className="kpi-v">
        {v}
        {unit && <i>{unit}</i>}
      </span>
    </div>
  );
}
