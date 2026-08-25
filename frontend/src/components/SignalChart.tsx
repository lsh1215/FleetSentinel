import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { telemetryStore } from "../lib/telemetryStore";

/**
 * 신호 시계열 차트.
 *
 * ## 왜 uPlot인가
 *
 * 캔버스 한 장에 직접 그리고 DOM을 만들지 않는다. 초당 수십 번 갱신되는 창에서
 * SVG 기반 차트(Recharts·Victory 등)는 점 하나당 DOM 노드를 만들어 감당하지 못한다.
 *
 * ## 왜 setData를 rAF에서 호출하는가
 *
 * 데이터는 초당 수십 번 들어오지만 화면은 60fps를 넘길 수 없다. 도착할 때마다 그리면
 * 같은 프레임 안에서 여러 번 그리는 낭비가 생긴다. rAF에 맞춰 **프레임당 한 번만** 그린다.
 *
 * 링 버퍼가 `Float64Array` 뷰를 그대로 돌려주므로 매 프레임 배열을 새로 만들지 않는다.
 */
interface Props {
  vehicleId: string | null;
  metric: "speed" | "steering" | "yawRate";
  label: string;
  unit: string;
  color: string;
}

export function SignalChart({ vehicleId, metric, label, unit, color }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const rafRef = useRef<number>(0);
  const vehicleRef = useRef(vehicleId);
  vehicleRef.current = vehicleId;

  useEffect(() => {
    if (!hostRef.current) return;
    const host = hostRef.current;

    const make = (width: number) =>
      new uPlot(
        {
          width,
          height: 116,
          padding: [8, 8, 0, 0],
          cursor: { show: true, x: true, y: false, drag: { x: false, y: false } },
          legend: { show: false },
          scales: { x: { time: false } },
          axes: [
            {
              stroke: "#64748b",
              grid: { stroke: "#1e293b", width: 1 },
              ticks: { stroke: "#1e293b" },
              size: 24,
              values: (_u, ticks) => ticks.map((t) => `${(t / 1000).toFixed(0)}s`),
            },
            {
              stroke: "#64748b",
              grid: { stroke: "#1e293b", width: 1 },
              ticks: { stroke: "#1e293b" },
              size: 42,
            },
          ],
          series: [{}, { stroke: color, width: 1.5, points: { show: false } }],
        },
        [new Float64Array(0), new Float64Array(0)],
        host,
      );

    plotRef.current = make(host.clientWidth || 320);

    // 컨테이너 크기 변화에 맞춘다. uPlot은 자동 반응형이 아니다.
    const ro = new ResizeObserver(([entry]) => {
      const w = entry?.contentRect.width ?? 0;
      if (w > 0) plotRef.current?.setSize({ width: w, height: 116 });
    });
    ro.observe(host);

    const tick = () => {
      rafRef.current = requestAnimationFrame(tick);
      const id = vehicleRef.current;
      const plot = plotRef.current;
      if (!plot) return;
      const v = id ? telemetryStore.getVehicle(id) : undefined;
      if (!v) {
        plot.setData([new Float64Array(0), new Float64Array(0)]);
        return;
      }
      const [xs, ys] = v.series[metric].view();
      // false = 스케일 자동 재계산을 건너뛰지 않음. 데이터 범위가 계속 바뀌므로 필요하다.
      plot.setData([xs, ys]);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [metric, color]);

  const v = vehicleId ? telemetryStore.getVehicle(vehicleId) : undefined;
  const last = v?.series[metric].last;

  return (
    <div className="chart">
      <div className="chart-head">
        <span className="chart-label">{label}</span>
        <span className="chart-value" style={{ color }}>
          {last == null ? "—" : `${last.toFixed(2)} ${unit}`}
        </span>
      </div>
      <div ref={hostRef} className="chart-host" />
    </div>
  );
}
