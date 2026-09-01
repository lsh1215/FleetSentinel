package io.fleetsentinel.gateway.ack;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/**
 * {@code exploration/tests/test_shipping.py}의 AckTracker 케이스를 옮긴 것이다.
 * 두 구현이 같은 계약을 지켜야 재생기에서 검증한 결과가 게이트웨이에도 적용된다.
 */
class AckTrackerTest {

    private static final long T0 = 1_000_000_000L;

    private static AckTracker tracker(long startSeq) {
        return new AckTracker(startSeq, 4, Duration.ofMillis(200), T0);
    }

    @Nested
    @DisplayName("CACK 계산")
    class Cack {

        @Test
        @DisplayName("연속 완료만 ack을 전진시킨다")
        void contiguousOnly() {
            var t = tracker(0);
            t.complete(0);
            t.complete(1);
            assertThat(t.ackSeq()).isEqualTo(1);

            // 2를 건너뛰고 3을 완료 — ack은 1에 머문다
            t.complete(3);
            assertThat(t.ackSeq()).isEqualTo(1);
            assertThat(t.pending()).isEqualTo(1);

            // 구멍이 메워지는 순간 3까지 한 번에 전진한다
            t.complete(2);
            assertThat(t.ackSeq()).isEqualTo(3);
            assertThat(t.pending()).isZero();
        }

        @Test
        @DisplayName("완료 순서가 뒤바뀌어도 결과가 같다")
        void orderIndependent() {
            List<Long> seqs = new ArrayList<>();
            for (long i = 0; i < 64; i++) {
                seqs.add(i);
            }
            Collections.shuffle(seqs, new java.util.Random(42));

            var t = tracker(0);
            seqs.forEach(t::complete);
            assertThat(t.ackSeq()).isEqualTo(63);
            assertThat(t.pending()).isZero();
        }

        @Test
        @DisplayName("이미 ack한 구간의 중복 완료는 무시한다")
        void duplicateCompleteIgnored() {
            var t = tracker(0);
            t.complete(0);
            t.complete(1);
            t.complete(0); // 재전송분이 다시 성공한 경우
            assertThat(t.ackSeq()).isEqualTo(1);
            assertThat(t.pending()).isZero();
        }

        @Test
        @DisplayName("스트림이 0이 아닌 seq에서 재개해도 성립한다")
        void resumeFromNonZero() {
            // 차량이 committed+1부터 재전송한다. 게이트웨이는 그 값이 무엇이든 받는다.
            var t = tracker(5000);
            assertThat(t.ackSeq()).isEqualTo(4999);
            t.complete(5000);
            assertThat(t.ackSeq()).isEqualTo(5000);
        }
    }

    @Nested
    @DisplayName("방출 주기")
    class Emission {

        @Test
        @DisplayName("everyN만큼 전진해야 방출한다")
        void everyN() {
            var t = tracker(0);
            t.complete(0);
            t.complete(1);
            assertThat(t.take(T0)).isEmpty(); // 2 < everyN=4

            t.complete(2);
            t.complete(3);
            assertThat(t.take(T0)).hasValue(3);
        }

        @Test
        @DisplayName("전진량이 적어도 시간이 지나면 방출한다 — 저부하에서 커밋이 멈추지 않게")
        void everyDuration() {
            var t = tracker(0);
            t.complete(0);
            assertThat(t.take(T0)).isEmpty();

            long later = T0 + Duration.ofMillis(250).toNanos();
            assertThat(t.take(later)).hasValue(0);
        }

        @Test
        @DisplayName("같은 값을 두 번 방출하지 않는다")
        void noRepeat() {
            var t = tracker(0);
            for (long i = 0; i < 4; i++) {
                t.complete(i);
            }
            assertThat(t.take(T0)).hasValue(3);

            long later = T0 + Duration.ofMillis(250).toNanos();
            assertThat(t.take(later)).isEmpty(); // ack이 전진하지 않았다
        }

        @Test
        @DisplayName("drain은 주기를 무시하고 흘려보낸다 — 스트림 종료 시 불필요한 재전송을 막는다")
        void drainIgnoresCadence() {
            var t = tracker(0);
            t.complete(0);
            t.complete(1);
            assertThat(t.take(T0)).isEmpty();

            assertThat(t.drain()).hasValue(1);
            assertThat(t.drain()).isEmpty(); // 두 번 흘리지 않는다
        }
    }

    @Nested
    @DisplayName("유실 방지 계약")
    class LossPrevention {

        @Test
        @DisplayName("쓰기가 실패한 seq 이상은 ack되지 않는다")
        void failedWriteBlocksAck() {
            // seq 10의 Kafka 쓰기가 실패했다고 가정 — complete()를 부르지 않는다.
            var t = tracker(0);
            for (long i = 0; i < 20; i++) {
                if (i != 10) {
                    t.complete(i);
                }
            }
            // 9까지만 안전하다. 차량은 10부터 재전송한다 — 그래서 유실이 아니다.
            assertThat(t.ackSeq()).isEqualTo(9);
            assertThat(t.pending()).isEqualTo(9); // 11..19
        }

        @Test
        @DisplayName("maxPending이 자라면 어떤 쓰기가 끝나지 않고 있다는 신호다")
        void maxPendingIsObservable() {
            var t = tracker(0);
            t.complete(0);
            for (long i = 2; i <= 5; i++) {
                t.complete(i);
            }
            assertThat(t.maxPending()).isEqualTo(4);

            t.complete(1);
            assertThat(t.pending()).isZero();
            assertThat(t.maxPending()).isEqualTo(4); // 최고 수위는 유지된다
        }
    }
}
