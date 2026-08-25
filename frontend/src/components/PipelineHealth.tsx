import { useEffect, useState } from "react";
import { telemetryStore } from "../lib/telemetryStore";

/**
 * 파이프라인 상태.
 *
 * **제품 데이터와 운영 메트릭은 다른 것**이라 경로를 분리한다(docs/sdd.md §6.1).
 * 차량 텔레메트리는 SSE로 밀려오지만, 파이프라인 상태는 초당 수천 건일 이유가 없으므로
 * 2초 폴링으로 충분하다. 굳이 스트림에 실으면 대역폭만 쓰고 얻는 게 없다.
 */
interface Health {
  kafka_consumer_lag: number;
  dlq_count: number;
  checkpoint_ms: number;
  checkpoint_failed: number;
  brokers_in_sync: number;
}

export function PipelineHealth({ streamStatus }: { streamStatus: string }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [throughput, setThroughput] = useState({ rec: 0, batch: 0 });

  useEffect(() => {
    let alive = true;
    const ctrl = new AbortController();
    const poll = async () => {
      try {
        const r = await fetch("/api/health", { signal: ctrl.signal });
        if (alive) setHealth(await r.json());
      } catch {
        /* 폴링 실패는 조용히 넘긴다 — 다음 주기에 다시 시도한다 */
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    // 처리량은 저장소가 자체 계측한다. 1초마다 읽어 표시만 한다.
    const tid = setInterval(
      () => setThroughput({ rec: telemetryStore.recordsPerSec, batch: telemetryStore.batchesPerSec }),
      1000,
    );
    return () => {
      alive = false;
      ctrl.abort();
      clearInterval(id);
      clearInterval(tid);
    };
  }, []);

  const dlqBad = (health?.dlq_count ?? 0) > 0;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>파이프라인</h2>
        <span className={`badge s-${streamStatus}`}>{streamStatus}</span>
      </div>
      <dl className="health">
        <div>
          <dt>수신 처리량</dt>
          <dd>
            {throughput.rec.toLocaleString()} <i>rec/s</i>
            <span className="sub">배치 {throughput.batch}/s</span>
          </dd>
        </div>
        <div>
          <dt>Kafka lag</dt>
          <dd>{health?.kafka_consumer_lag ?? "—"}</dd>
        </div>
        <div className={dlqBad ? "bad" : ""}>
          <dt>DLQ</dt>
          <dd>{health?.dlq_count ?? "—"}</dd>
        </div>
        <div>
          <dt>체크포인트</dt>
          <dd>
            {health ? `${health.checkpoint_ms}ms` : "—"}
            <span className="sub">실패 {health?.checkpoint_failed ?? "—"}</span>
          </dd>
        </div>
        <div>
          <dt>ISR</dt>
          <dd>{health ? `${health.brokers_in_sync}/3` : "—"}</dd>
        </div>
      </dl>
    </div>
  );
}
