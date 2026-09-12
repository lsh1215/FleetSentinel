package io.fleetsentinel.pipeline.dedup;

import java.io.Serializable;
import java.util.Arrays;

/**
 * 차량 하나의 seq 슬라이딩 윈도우 비트맵. 차량 쪽 dedup.py 의 SeqDedup 을 옮긴 것이다.
 *
 * 본 적 있는 seq 를 전부 기억하면 상태가 데이터 양에 비례해 늘어난다 — 실측 124.8 GB다.
 * 최근 W개만 비트로 들고 있으면 차량당 W/8 바이트로 고정된다(W=4096이면 512 B).
 * 데이터가 50배 늘어도 상태 크기는 그대로다.
 *
 * 비트는 seq % W 자리에 넣는다. 윈도우가 앞으로 갈 때 비트를 옮기지 않고, 새로 들어오는
 * 자리만 비운다. 그 자리는 비우기 전까지 W개 전의 seq 를 담고 있으므로, 비우기 전에 읽어야
 * 그 seq 가 도착했는지 알 수 있다 — 유실을 세는 근거가 이것이다.
 *
 * Flink 상태에 담기므로 Serializable 이어야 한다.
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
     * 이 레코드를 하류로 넘겨야 하는지 판정한다.
     *
     * 판정은 멱등하다 — 같은 인자로 다시 부르면 DUPLICATE 다. 그래서 재생기가 같은
     * 구간을 다시 보내도 하류가 보는 것은 한 번뿐이다.
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
     * lastSeen 을 seq 까지 밀면서, 윈도우 밖으로 밀려나는 구멍을 유실로 확정한다.
     * 자리를 비우기 전에 읽어야 밀려나가는 seq 가 도착했었는지 알 수 있다.
     */
    private void advance(long seq) {
        long prev = lastSeen;
        long end = Math.min(seq, prev + window);

        for (long n = prev + 1; n <= end; n++) {
            // n 이 들어올 자리에는 지금 W개 전인 old 가 들어 있다(같은 자리를 돌려쓴다).
            long old = n - window;
            if (old > contiguous) {
                if (!test(old)) {       // 비트가 꺼져 있다 = 끝내 안 왔다 = 유실
                    lost++;
                }
                contiguous = old;
            }
            clear(n);                   // 이제 이 자리를 n 이 쓴다
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

    /** 구멍이 메워졌으면 contiguous 를 그만큼 앞으로 당긴다. */
    private void pullContiguous() {
        while (contiguous < lastSeen && test(contiguous + 1)) {
            contiguous++;
        }
    }

    /** seq 가 쓸 자리 번호. mask 가 window-1 이라 seq % window 와 같은 값이다. */
    private int index(long seq) {
        return (int) (seq & mask);
    }

    // 아래 셋은 비트 하나를 읽고·켜고·끈다. 비트는 byte[] 에 8개씩 들어 있어서
    // i >> 3 으로 몇 번째 바이트인지(i / 8), i & 7 로 그 바이트 안 몇 번째 비트인지(i % 8)를 구한다.
    // 1 << (i & 7) 은 그 비트 자리만 1인 값이라, & 로 읽고 |= 로 켜고 &= ~ 로 끈다.

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
