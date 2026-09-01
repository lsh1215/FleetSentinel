package io.fleetsentinel.pipeline.dedup;

import java.io.Serializable;
import java.util.Arrays;

/**
 * 차량 하나의 `seq` 슬라이딩 윈도우 비트맵.
 *
 * <p>{@code exploration/fleetsentinel_ingest/dedup.py}의 {@code SeqDedup}을 옮긴 것이다.
 * 계약이 그쪽 테스트 14건으로 고정돼 있어 포팅은 같은 케이스를 옮기는 작업이 된다.
 *
 * <h2>왜 비트맵인가</h2>
 *
 * <p>본 적 있는 `seq`를 전부 기억하면 상태가 데이터 양에 비례한다 — 실측으로 124.8 GB다.
 * 대신 <b>최근 W개만</b> 비트로 들고 있으면 차량당 W/8 바이트로 고정된다(W=4096이면 512 B).
 * 데이터가 50배 늘어도 상태는 그대로다.
 *
 * <h2>환형 버퍼</h2>
 *
 * <p>비트는 {@code seq % W}로 인덱싱한다. 윈도우가 전진할 때 비트를 옮기지 않고
 * <b>새로 들어오는 슬롯만 비운다.</b> 슬롯 {@code n % W}는 비우기 전에 {@code n - W}를
 * 담고 있으므로, <b>비우기 전에 읽어야</b> 그 `seq`가 도착했는지 알 수 있다 —
 * 이게 유실 계수의 근거다.
 *
 * <p>이 클래스는 Flink keyed state에 담기므로 {@link Serializable} 이어야 한다.
 */
public final class SeqWindow implements Serializable {

    private static final long serialVersionUID = 1L;

    /** 순서 역전을 허용하는 폭. 1,308 rec/s에서 약 3.1초분이다. */
    public static final int DEFAULT_WINDOW = 4096;

    private final int window;
    private final int mask;

    /** 이 차량의 현재 WAL 세션. 바뀌면 `seq`가 0부터 다시 시작한다. */
    private String bootId;

    /** 지금까지 본 최고 `seq`. */
    private long lastSeen;

    /** 구멍 없이 이어진 최고 `seq`. 이 아래는 판정이 끝났다. */
    private long contiguous;

    /** 윈도우 밖으로 밀려나며 유실로 확정된 수. */
    private long lost;

    private byte[] bits;

    public SeqWindow() {
        this(DEFAULT_WINDOW);
    }

    public SeqWindow(int window) {
        if (window <= 0 || (window & (window - 1)) != 0) {
            throw new IllegalArgumentException("window는 2의 거듭제곱이어야 한다: " + window);
        }
        this.window = window;
        this.mask = window - 1;
        this.bits = new byte[window / 8];
        this.bootId = null;
        this.lastSeen = -1;
        this.contiguous = -1;
    }

    public long lastSeen() {
        return lastSeen;
    }

    public long contiguous() {
        return contiguous;
    }

    public long lost() {
        return lost;
    }

    public String bootId() {
        return bootId;
    }

    /**
     * 이 레코드를 하류로 넘겨야 하면 {@link Verdict#ACCEPT}.
     *
     * <p><b>판정은 멱등하다</b> — 같은 인자로 다시 부르면 {@code DUPLICATE}다.
     * 그래서 재생기가 같은 구간을 다시 보내도 하류가 보는 것은 정확히 한 번이다.
     */
    public Verdict accept(String boot, long seq) {
        if (bootId == null) {
            // 첫 레코드. 이 아래는 확인할 방법이 없으므로 정상이라고 가정한다 —
            // Flink 상태가 체크포인트에서 복구되지 않은 경우에만 해당한다.
            reset(boot, seq);
        } else if (!bootId.equals(boot)) {
            // WAL이 사라졌다 → `seq`가 0부터 다시 시작한다.
            // 리셋하지 않으면 "이미 봤다"고 전량을 버린다 = 전량 유실.
            reset(boot, seq);
            advance(seq);
            return Verdict.BOOT_RESET;
        }

        if (seq > lastSeen) {
            advance(seq);
            return Verdict.ACCEPT;
        }
        if (seq <= lastSeen - window) {
            // 윈도우 밖. 진짜 새 레코드였을 수 있으므로 계수해서 드러낸다 —
            // 조용히 버리면 유실이 관측되지 않는다.
            return Verdict.TOO_OLD;
        }
        if (test(seq)) {
            return Verdict.DUPLICATE;
        }
        // 순서 역전으로 늦게 도착한 새 레코드. `lastSeen` 하나만 뒀다면 버렸을 것이다.
        set(seq);
        pullContiguous();
        return Verdict.LATE;
    }

    private void reset(String boot, long seq) {
        this.bootId = boot;
        this.lastSeen = seq - 1;
        this.contiguous = seq - 1;
        this.lost = 0;
        Arrays.fill(bits, (byte) 0);
    }

    /**
     * `lastSeen`을 `seq`까지 밀면서 밀려나가는 구멍을 유실로 확정한다.
     *
     * <p>슬롯을 <b>비우기 전에 읽어야</b> 한다 — 그래야 밀려나가는 `seq`가 도착했는지 안다.
     */
    private void advance(long seq) {
        long prev = lastSeen;
        long end = Math.min(seq, prev + window);

        for (long n = prev + 1; n <= end; n++) {
            long old = n - window;
            if (old > contiguous) {
                if (!test(old)) {       // old와 n은 같은 슬롯이다
                    lost++;
                }
                contiguous = old;
            }
            clear(n);
        }

        if (seq > end) {
            // 점프가 윈도우보다 크다 — 전체 슬롯이 이미 무효화됐다.
            Arrays.fill(bits, (byte) 0);
            long floor = seq - window;
            if (floor > contiguous) {
                // 이 구간은 도착한 적이 없다(미래였으므로). 전부 유실.
                lost += floor - contiguous;
                contiguous = floor;
            }
        }

        lastSeen = seq;
        set(seq);
        pullContiguous();
    }

    private void pullContiguous() {
        while (contiguous < lastSeen && test(contiguous + 1)) {
            contiguous++;
        }
    }

    private int index(long seq) {
        return (int) (seq & mask);
    }

    private boolean test(long seq) {
        int i = index(seq);
        return (bits[i >> 3] & (1 << (i & 7))) != 0;
    }

    private void set(long seq) {
        int i = index(seq);
        bits[i >> 3] |= (byte) (1 << (i & 7));
    }

    private void clear(long seq) {
        int i = index(seq);
        bits[i >> 3] &= (byte) ~(1 << (i & 7));
    }

    /** 판정 결과. ACCEPT·LATE·BOOT_RESET만 하류로 넘어간다. */
    public enum Verdict {
        /** 새 레코드. 정상 전진 */
        ACCEPT(true),
        /** 순서 역전으로 늦게 왔지만 처음 보는 것 */
        LATE(true),
        /** `boot_id`가 바뀌어 상태를 리셋했다. 이 레코드는 통과시킨다 */
        BOOT_RESET(true),
        /** 이미 본 것. 재전송분이다 */
        DUPLICATE(false),
        /** 윈도우 밖. 유실일 수 있다 */
        TOO_OLD(false);

        private final boolean pass;

        Verdict(boolean pass) {
            this.pass = pass;
        }

        public boolean pass() {
            return pass;
        }
    }
}
