package io.fleetsentinel.gateway.storage;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.regex.Pattern;

/**
 * 오브젝트 키 생성. <b>권한 경계가 이 문자열에 박힌다.</b>
 *
 * <pre>
 * v1/vehicle_id=vehicle-0042/date=2026-08-28/01K3...ABC.mcap
 *    └──── 인증서에서 나온 값 ────┘
 * </pre>
 *
 * presigned URL은 키를 서명에 포함하므로, 차량 A가 받은 URL로는 A의 경로에만 쓸 수 있다.
 * 키를 바꾸면 서명이 깨진다 — [중량 경로 설계](heavy-path-design.md) §2.3.
 */
public final class SegmentKey {

    private static final DateTimeFormatter DATE =
            DateTimeFormatter.ofPattern("yyyy-MM-dd").withZone(ZoneOffset.UTC);

    /**
     * 키에 들어가도 안전한 값인지 검사한다. 경로 탈출(`..`)이나 구분자(`/`)가 들어오면
     * 다른 차량의 접두사로 넘어갈 수 있다.
     *
     * <p>{@code vehicle_id}는 인증서 SAN에서 오고 그쪽이 이미 같은 패턴으로 제한하지만
     * (VehicleIdentity), 키를 만드는 지점에서 한 번 더 막는다 — 신원 추출 규칙이 나중에
     * 느슨해져도 여기서 걸린다.
     */
    private static final Pattern SAFE = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$");

    private SegmentKey() {
    }

    /**
     * @param tStartUs 클립 시작 시각(epoch micros). <b>업로드 시각이 아니다</b> —
     *                 재연결 지연으로 며칠 뒤 올라온 클립이 엉뚱한 파티션에 들어가면
     *                 시간 기반 질의가 깨진다(§3)
     */
    public static String of(String keyPrefix, String vehicleId, String segmentId, long tStartUs) {
        require(vehicleId, "vehicle_id");
        require(segmentId, "segment_id");
        String date = DATE.format(Instant.ofEpochSecond(
                Math.floorDiv(tStartUs, 1_000_000L),
                Math.floorMod(tStartUs, 1_000_000L) * 1_000L));
        return "%s/vehicle_id=%s/date=%s/%s.mcap".formatted(keyPrefix, vehicleId, date, segmentId);
    }

    private static void require(String value, String what) {
        if (value == null || !SAFE.matcher(value).matches()) {
            throw new IllegalArgumentException(
                    "키에 쓸 수 없는 " + what + ": " + value);
        }
    }
}
