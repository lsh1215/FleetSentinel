package io.fleetsentinel.gateway.storage;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 오브젝트 키 계약. <b>권한 경계가 이 문자열에 박히므로</b> 여기가 뚫리면 차량이 남의
 * 경로에 쓸 수 있다([중량 경로 설계](heavy-path-design.md) §2.3).
 */
class SegmentKeyTest {

    /** 2018-07-24T03:28:47.604844Z — scene-0061의 실제 t_start. */
    private static final long T = 1_532_402_927_604_844L;

    @Test
    @DisplayName("키는 (prefix, vehicle_id, date, segment_id)의 순수 함수다")
    void deterministic() {
        String a = SegmentKey.of("v1", "vehicle-0042", "01K3ABC", T);
        String b = SegmentKey.of("v1", "vehicle-0042", "01K3ABC", T);
        assertThat(a).isEqualTo(b).isEqualTo(
                "v1/vehicle_id=vehicle-0042/date=2018-07-24/01K3ABC.mcap");
    }

    @Test
    @DisplayName("date는 t_start의 UTC 날짜다 — 업로드 시각이 아니다")
    void datePartitionComesFromTStart() {
        assertThat(SegmentKey.of("v1", "v", "s", T)).contains("date=2018-07-24");
    }

    @Test
    @DisplayName("UTC 자정 경계에서 날짜가 넘어간다")
    void utcMidnightBoundary() {
        long justBefore = 1_532_390_399_999_999L;  // 2018-07-23T23:59:59.999999Z
        long justAfter = 1_532_390_400_000_000L;   // 2018-07-24T00:00:00Z
        assertThat(SegmentKey.of("v1", "v", "s", justBefore)).contains("date=2018-07-23");
        assertThat(SegmentKey.of("v1", "v", "s", justAfter)).contains("date=2018-07-24");
    }

    @Test
    @DisplayName("경로 탈출을 막는다 — 이게 뚫리면 남의 접두사로 넘어간다")
    void rejectsPathEscape() {
        for (String evil : List.of("../vehicle-0002", "a/b", "..", "/etc/passwd",
                "vehicle-0001/../vehicle-0002", "")) {
            assertThatThrownBy(() -> SegmentKey.of("v1", evil, "01K3", T))
                    .as("거절해야 한다: %s", evil)
                    .isInstanceOf(IllegalArgumentException.class);
            assertThatThrownBy(() -> SegmentKey.of("v1", "vehicle-0001", evil, T))
                    .as("segment_id로도 거절해야 한다: %s", evil)
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    @DisplayName("다른 차량은 항상 다른 접두사를 갖는다")
    void prefixIsolation() {
        String a = SegmentKey.of("v1", "vehicle-0001", "same-id", T);
        String b = SegmentKey.of("v1", "vehicle-0002", "same-id", T);
        assertThat(a).startsWith("v1/vehicle_id=vehicle-0001/");
        assertThat(b).startsWith("v1/vehicle_id=vehicle-0002/");
        assertThat(a).isNotEqualTo(b);
    }
}
