package io.fleetsentinel.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import tools.jackson.databind.ObjectMapper;
import io.fleetsentinel.api.query.TelemetryQueries;
import io.fleetsentinel.api.web.QueryController;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * 응답 <b>JSON 형태</b>가 프론트 계약과 맞는지 고정한다.
 *
 * <p>프론트를 고치지 않는 것이 목적이므로, 키 이름이 바뀌면 대시보드가 <b>조용히 빈
 * 화면</b>이 된다 — 예외가 안 나서 눈으로는 못 잡는다. 그걸 여기서 잡는다.
 *
 * <p>MVC 슬라이스를 쓰지 않고 컨트롤러를 직접 부른 뒤 Jackson 으로 직렬화한다. 검증
 * 대상이 라우팅이 아니라 <b>페이로드 형태</b>라서, 프레임워크를 끌어올 이유가 없다.
 */
class ContractTest {

    private final TelemetryQueries queries = mock(TelemetryQueries.class);
    private final QueryController controller = new QueryController(queries);
    // Jackson 3 — Boot 4 기본. 패키지가 tools.jackson 으로 바뀌었다.
    private final ObjectMapper json = new ObjectMapper();

    @Test
    @DisplayName("/api/vehicles 는 { vehicles: [...] } 로 감싼다")
    void vehiclesShape() throws Exception {
        when(queries.vehicles()).thenReturn(List.of(orderedMap(
                "vehicle_id", "vehicle-0001",
                "scene_name", "scene-0061",
                "location", "singapore-onenorth",
                "duration_ms", 19500L,
                "home", List.of(1.2988, 103.7884))));

        var node = json.valueToTree(controller.vehicles());

        // 프론트가 m.vehicles 로 꺼낸다(App.tsx)
        assertThat(node.has("vehicles")).isTrue();
        var v = node.get("vehicles").get(0);
        assertThat(v.get("vehicle_id").asText()).isEqualTo("vehicle-0001");
        assertThat(v.get("location").asText()).isEqualTo("singapore-onenorth");
        // 지도 초기 중심. 없으면 지도가 엉뚱한 곳을 본다.
        assertThat(v.get("home").isArray()).isTrue();
        // 프론트 telemetryStore 가 쓰는 키
        assertThat(v.has("scene_name")).isTrue();
    }

    @Test
    @DisplayName("/api/clips 는 배열을 그대로 준다 — 감싸지 않는다")
    void clipsShape() throws Exception {
        when(queries.clips(anyInt())).thenReturn(List.of(orderedMap(
                "clip_id", "01K3ABC",
                "vehicle_id", "vehicle-0001",
                "blob_uri", "s3://fleet-raw/v1/…",
                "duration_s", 19.2)));

        var node = json.valueToTree(controller.clips(100));

        assertThat(node.isArray()).isTrue();
        assertThat(node.get(0).get("clip_id").asText()).isEqualTo("01K3ABC");
        // Claim-Check — 파일은 스토리지에 있고 여기엔 참조만 있다(SDD S-1)
        assertThat(node.get(0).has("blob_uri")).isTrue();
    }

    @Test
    @DisplayName("/api/health 는 total_missing 을 낸다 — 결번이 곧 유실이다")
    void healthShape() throws Exception {
        when(queries.health()).thenReturn(orderedMap(
                "counts", Map.of("signals", 51025L),
                "total_missing", 0L,
                "vehicles", List.of(Map.of("vehicle_id", "vehicle-0001", "missing", 0L)),
                "dup_pressure", List.of(Map.of("table", "signals", "pending_dupes", 0L))));

        var node = json.valueToTree(controller.health());

        assertThat(node.get("total_missing").asLong()).isZero();
        assertThat(node.get("counts").get("signals").asLong()).isEqualTo(51025);
        // 머지 대기 중복. 여기만 _raw 를 본다 — 중복 자체가 관측 대상이다(SDD L-14)
        assertThat(node.get("dup_pressure").isArray()).isTrue();
    }

    @Test
    @DisplayName("clips 의 limit 에 상한을 건다 — 무제한이면 브라우저가 먼저 무너진다")
    void clipsLimitIsCapped() {
        when(queries.clips(anyInt())).thenReturn(List.of());
        controller.clips(999_999);

        ArgumentCaptor<Integer> cap = ArgumentCaptor.forClass(Integer.class);
        verify(queries).clips(cap.capture());
        assertThat(cap.getValue()).isLessThanOrEqualTo(1000);
    }

    /** {@code Map.of} 는 순서를 보장하지 않아 JSON 키 순서 확인에 부적합하다. */
    private static Map<String, Object> orderedMap(Object... kv) {
        var m = new java.util.LinkedHashMap<String, Object>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], kv[i + 1]);
        }
        return m;
    }
}
