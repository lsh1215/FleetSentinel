package io.fleetsentinel.pipeline.dedup;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.fleetsentinel.pipeline.dedup.SeqWindow.Verdict;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/**
 * {@code exploration/tests/test_dedup.py}의 케이스를 옮긴 것이다.
 * 두 구현이 같은 판정을 내려야 재생기에서 검증한 결과가 Flink에도 적용된다.
 */
class SeqWindowTest {

    private static final String BOOT = "boot-a";

    @Nested
    @DisplayName("기본 판정")
    class Basic {

        @Test
        @DisplayName("순차 도착은 전부 통과한다")
        void sequential() {
            var w = new SeqWindow(64);
            for (long i = 0; i < 200; i++) {
                assertThat(w.accept(BOOT, i)).isEqualTo(Verdict.ACCEPT);
            }
            assertThat(w.lastSeen()).isEqualTo(199);
            assertThat(w.contiguous()).isEqualTo(199);
            assertThat(w.lost()).isZero();
        }

        @Test
        @DisplayName("같은 seq를 다시 주면 중복이다 — 판정이 멱등하다")
        void duplicateIsIdempotent() {
            var w = new SeqWindow(64);
            w.accept(BOOT, 0);
            w.accept(BOOT, 1);
            assertThat(w.accept(BOOT, 1)).isEqualTo(Verdict.DUPLICATE);
            assertThat(w.accept(BOOT, 1)).isEqualTo(Verdict.DUPLICATE);
            assertThat(w.accept(BOOT, 0)).isEqualTo(Verdict.DUPLICATE);
        }

        @Test
        @DisplayName("순서 역전으로 늦게 온 새 레코드는 통과시킨다")
        void lateButNew() {
            var w = new SeqWindow(64);
            w.accept(BOOT, 0);
            w.accept(BOOT, 5);                       // 1~4를 건너뛰었다
            assertThat(w.contiguous()).isEqualTo(0);

            assertThat(w.accept(BOOT, 3)).isEqualTo(Verdict.LATE);
            assertThat(w.accept(BOOT, 3)).isEqualTo(Verdict.DUPLICATE);  // 두 번째는 중복
            assertThat(w.accept(BOOT, 1)).isEqualTo(Verdict.LATE);
            assertThat(w.accept(BOOT, 2)).isEqualTo(Verdict.LATE);
            assertThat(w.contiguous()).isEqualTo(3);  // 1,2,3이 메워져 3까지 이어졌다
        }

        @Test
        @DisplayName("윈도우 밖은 too_old다 — 조용히 버리지 않고 드러낸다")
        void tooOld() {
            var w = new SeqWindow(64);
            for (long i = 0; i < 200; i++) {
                w.accept(BOOT, i);
            }
            assertThat(w.accept(BOOT, 10)).isEqualTo(Verdict.TOO_OLD);
        }
    }

    @Nested
    @DisplayName("유실 계수")
    class Loss {

        @Test
        @DisplayName("결번이 윈도우 밖으로 밀려나면 유실로 확정한다")
        void gapBecomesLoss() {
            var w = new SeqWindow(64);
            w.accept(BOOT, 0);
            // 1을 건너뛰고 계속 보낸다
            for (long i = 2; i < 200; i++) {
                w.accept(BOOT, i);
            }
            // seq 1은 윈도우 밖으로 밀려났다 = 탐지된 유실
            assertThat(w.lost()).isEqualTo(1);
        }

        @Test
        @DisplayName("정상 스트림에서는 유실이 0이다 — 거짓 양성이 없다")
        void noFalsePositive() {
            var w = new SeqWindow(4096);
            for (long i = 0; i < 50_000; i++) {
                w.accept(BOOT, i);
            }
            assertThat(w.lost()).isZero();
        }

        @Test
        @DisplayName("윈도우보다 큰 점프는 그 구간 전체가 유실이다")
        void jumpBeyondWindow() {
            var w = new SeqWindow(64);
            w.accept(BOOT, 0);
            w.accept(BOOT, 1000);            // 1~999가 통째로 사라졌다
            // floor = 1000 - 64 = 936. contiguous 0 → 936 으로 밀리며 936건 유실
            assertThat(w.lost()).isEqualTo(936);
            assertThat(w.contiguous()).isEqualTo(936);
        }
    }

    @Nested
    @DisplayName("boot_id 리셋")
    class BootReset {

        @Test
        @DisplayName("boot_id가 바뀌면 상태를 리셋한다 — 안 하면 전량 유실")
        void resetOnNewBoot() {
            var w = new SeqWindow(64);
            for (long i = 0; i < 100; i++) {
                w.accept(BOOT, i);
            }
            // WAL이 지워져 seq가 0부터 다시 시작한다.
            // 리셋하지 않으면 "이미 봤다"고 전부 버린다.
            assertThat(w.accept("boot-b", 0)).isEqualTo(Verdict.BOOT_RESET);
            assertThat(w.accept("boot-b", 1)).isEqualTo(Verdict.ACCEPT);
            assertThat(w.bootId()).isEqualTo("boot-b");
            assertThat(w.lost()).isZero();
        }
    }

    @Nested
    @DisplayName("상태 크기")
    class StateSize {

        @Test
        @DisplayName("데이터가 늘어도 상태가 커지지 않는다")
        void constantState() {
            var small = new SeqWindow(4096);
            var large = new SeqWindow(4096);
            for (long i = 0; i < 1_000; i++) {
                small.accept(BOOT, i);
            }
            for (long i = 0; i < 50_000; i++) {
                large.accept(BOOT, i);
            }
            // 비트맵 크기는 window/8 로 고정이다. 50배 데이터에 상태 불변.
            assertThat(serializedSize(small)).isEqualTo(serializedSize(large));
        }

        private int serializedSize(SeqWindow w) {
            try (var bos = new java.io.ByteArrayOutputStream();
                 var oos = new java.io.ObjectOutputStream(bos)) {
                oos.writeObject(w);
                oos.flush();
                return bos.size();
            } catch (java.io.IOException e) {
                throw new IllegalStateException(e);
            }
        }
    }

    @Test
    @DisplayName("window는 2의 거듭제곱이어야 한다 — 아니면 마스크 인덱싱이 깨진다")
    void windowMustBePowerOfTwo() {
        assertThatThrownBy(() -> new SeqWindow(100))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new SeqWindow(0))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
