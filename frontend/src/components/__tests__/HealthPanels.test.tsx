import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { KpiStrip } from "../KpiStrip";
import { PipelineHealth } from "../PipelineHealth";

describe("health panels before metrics arrive", () => {
  it("does not report a zero DLQ count or an ISR warning", () => {
    const html = renderToStaticMarkup(<KpiStrip />);
    expect(html).toContain('<span class="kpi-k">dlq</span><span class="kpi-v">—</span>');
    expect(html).toContain('<span class="kpi-k">isr</span><span class="kpi-v">—</span>');
    expect(html).not.toContain("kpi-i warn");
    expect(html).not.toContain("kpi-i alarm");
  });

  it("leaves unavailable checkpoint and ISR values blank", () => {
    const html = renderToStaticMarkup(<PipelineHealth streamStatus="connecting" />);
    expect(html).toContain('<dt>체크포인트</dt><dd>—<span');
    expect(html).toContain('<dt>ISR</dt><dd>—</dd>');
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("0/3");
  });
});
