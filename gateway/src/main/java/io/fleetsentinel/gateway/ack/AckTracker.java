package io.fleetsentinel.gateway.ack;

import java.time.Duration;
import java.util.HashSet;
import java.util.OptionalLong;
import java.util.Set;

/**
 * 순서 없이 완료되는 Kafka 쓰기에서 CACK(Cumulative Acknowledgement)을 계산한다.
 *
 * <p>{@code exploration/fleetsentinel_ingest/shipping.py}의 {@code AckTracker}를 옮긴 것이다.
 * 계약이 그쪽 테스트 13건으로 고정돼 있어 포팅은 같은 케이스를 옮기는 작업이 된다.
 *
 * <h2>CACK이 정확히 성립하는 이유</h2>
 *
 * <p>Kafka producer 콜백은 파티션별로 순서대로 호출된다. 파티션 키가 {@code vehicle_id}이므로
 * 한 차량의 레코드는 한 파티션에 가고, 따라서 "연속으로 성공한 최고 seq"가 곧 "이 값 이하는
 * 전부 안전하다"가 된다. 그럼에도 이 클래스는 순서 없는 완료를 받아낸다 — 그 보장에 의존하지
 * 않는 편이 안전하고 비용도 없다.
 *
 * <h2>스레드 안전</h2>
 *
 * <p><b>이 클래스는 스레드 안전하지 않다.</b> {@code complete()}는 Kafka 프로듀서 IO 스레드에서,
 * {@code take()}는 gRPC 스트림 스레드에서 불릴 수 있다. 호출부가 하나의 락으로 감싸야 한다 —
 * {@code IngestService}가 스트림별 락으로 그렇게 한다. 여기서 락을 잡지 않는 이유는 ack 방출과
 * {@code StreamObserver.onNext()}가 <b>같은</b> 임계 구역이어야 하기 때문이다. 둘을 따로 잠그면
 * ack이 역순으로 나갈 수 있고, 그러면 차량이 커밋을 되돌린다.
 */
public final class AckTracker {

    /** ack 주기. 차량당 1,295 rec/s에서 128개 ≈ 99ms → 차량당 10 ack/s. */
    public static final int DEFAULT_EVERY_N = 128;

    /** 저부하(정차 등)에서도 커밋이 전진하도록 하는 상한. */
    public static final Duration DEFAULT_EVERY = Duration.ofMillis(200);

    private final int everyN;
    private final long everyNanos;

    /** 이 값 이하는 전부 Kafka 쓰기가 성공했다. */
    private long ack;

    /** 완료됐지만 아래에 구멍이 있어 ack할 수 없는 seq들. */
    private final Set<Long> done = new HashSet<>();

    private long lastEmitted;
    private long lastAtNanos;
    private int maxPending;

    /**
     * @param startSeq 이 스트림의 첫 seq. ack은 {@code startSeq - 1}에서 시작한다
     */
    public AckTracker(long startSeq, int everyN, Duration every, long nowNanos) {
        this.ack = startSeq - 1;
        this.lastEmitted = this.ack;
        this.everyN = everyN;
        this.everyNanos = every.toNanos();
        this.lastAtNanos = nowNanos;
    }

    public AckTracker(long startSeq, long nowNanos) {
        this(startSeq, DEFAULT_EVERY_N, DEFAULT_EVERY, nowNanos);
    }

    /** 이 값 이하는 <b>전부</b> Kafka 쓰기가 성공했다. */
    public long ackSeq() {
        return ack;
    }

    /**
     * 완료됐지만 그 아래에 구멍이 있어 ack할 수 없는 레코드 수.
     *
     * <p>이 값이 계속 자라면 어떤 레코드의 쓰기가 끝나지 않고 있다는 뜻이다.
     */
    public int pending() {
        return done.size();
    }

    public int maxPending() {
        return maxPending;
    }

    /** Kafka 쓰기 성공. 순서는 상관없다. */
    public void complete(long seq) {
        if (seq <= ack) {
            return; // 이미 ack한 구간의 중복 완료
        }
        done.add(seq);
        while (done.remove(ack + 1)) {
            ack++;
        }
        maxPending = Math.max(maxPending, done.size());
    }

    /**
     * 방출할 ack이 있으면 그 seq. 없으면 비어 있음.
     *
     * <p>같은 값을 두 번 방출하지 않는다 — ack이 전진하지 않았다면 보낼 이유가 없다.
     */
    public OptionalLong take(long nowNanos) {
        if (ack <= lastEmitted) {
            return OptionalLong.empty();
        }
        if (ack - lastEmitted >= everyN || nowNanos - lastAtNanos >= everyNanos) {
            lastEmitted = ack;
            lastAtNanos = nowNanos;
            return OptionalLong.of(ack);
        }
        return OptionalLong.empty();
    }

    /**
     * 주기 조건을 무시하고 지금까지의 ack을 방출한다. 스트림이 정상 종료될 때 쓴다.
     *
     * <p>이게 없으면 마지막 127개 이하가 ack되지 않은 채 스트림이 끝나고, 차량은 그만큼을
     * 재전송한다. 유실은 아니지만 불필요한 중복이다.
     */
    public OptionalLong drain() {
        if (ack <= lastEmitted) {
            return OptionalLong.empty();
        }
        lastEmitted = ack;
        return OptionalLong.of(ack);
    }
}
