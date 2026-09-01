package io.fleetsentinel.pipeline.dedup;

import io.fleetsentinel.pipeline.dedup.SeqWindow.Verdict;
import io.fleetsentinel.pipeline.model.Envelope;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.metrics.Counter;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.util.Collector;

/**
 * 차량별 중복 제거. <b>이 잡에서 keyed state를 쓰는 유일한 곳</b>이다.
 *
 * <p>{@code keyBy(vehicle_id)}가 앞에 있으므로 같은 차량의 레코드는 항상 같은 태스크로
 * 오고, {@link ValueState}가 그 차량만의 비트맵을 들고 있다. Kafka 파티션 키도
 * {@code vehicle_id}라 <b>셔플이 없다</b>.
 *
 * <h2>왜 게이트웨이가 아니라 여기인가</h2>
 *
 * <p>게이트웨이에 두면 인스턴스가 죽을 때 상태가 함께 사라져 중복이 그대로 저장 계층까지
 * 유입된다. Flink 상태는 체크포인트로 복구된다.
 *
 * <h2>이 연산자가 못 막는 것</h2>
 *
 * <p><b>Flink→ClickHouse 구간의 중복은 여기서 안 잡힌다.</b> 체크포인트 복구 시 이 상태도
 * 함께 되감기므로, 재생되는 레코드를 "처음 보는 것"으로 통과시킨다. 그 구간은
 * {@code ReplacingMergeTree} 멱등 upsert가 흡수한다(SDD L-14) — 두 장치가 서로 다른
 * 구멍을 닫는다.
 */
public class DedupFunction extends KeyedProcessFunction<String, Envelope, Envelope> {

    private static final long serialVersionUID = 1L;

    private final int window;

    private transient ValueState<SeqWindow> state;
    private transient Counter accepted;
    private transient Counter duplicate;
    private transient Counter late;
    private transient Counter tooOld;
    private transient Counter bootReset;

    public DedupFunction(int window) {
        this.window = window;
    }

    @Override
    public void open(OpenContext openContext) {
        state = getRuntimeContext().getState(
                new ValueStateDescriptor<>("seq-window", SeqWindow.class));

        var group = getRuntimeContext().getMetricGroup().addGroup("dedup");
        accepted = group.counter("accepted");
        duplicate = group.counter("duplicate");
        late = group.counter("late");
        // too_old 는 **유실일 수 있다** — 윈도우 밖으로 밀려난 뒤 도착한 것이므로.
        // 이 지표가 0이 아니면 윈도우를 키우거나 지연 원인을 봐야 한다.
        tooOld = group.counter("too_old");
        bootReset = group.counter("boot_reset");
    }

    @Override
    public void processElement(Envelope env, Context ctx, Collector<Envelope> out)
            throws Exception {
        SeqWindow w = state.value();
        if (w == null) {
            w = new SeqWindow(window);
        }

        Verdict verdict = w.accept(env.bootId(), env.seq());
        state.update(w);

        switch (verdict) {
            case ACCEPT -> accepted.inc();
            case LATE -> {
                late.inc();
                accepted.inc();
            }
            case BOOT_RESET -> {
                bootReset.inc();
                accepted.inc();
            }
            case DUPLICATE -> duplicate.inc();
            case TOO_OLD -> tooOld.inc();
        }

        if (verdict.pass()) {
            out.collect(env);
        }
    }
}
