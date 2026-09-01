package io.fleetsentinel.api.web;

import io.fleetsentinel.api.query.TelemetryQueries;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 조회 API. <b>경로와 응답 형태는 프론트가 이미 쓰고 있는 계약이다</b> —
 * 목업 스트림을 대체하는 것이 목적이므로 프론트를 고치지 않는다.
 */
@RestController
@RequestMapping("/api")
public class QueryController {

    private final TelemetryQueries queries;

    public QueryController(TelemetryQueries queries) {
        this.queries = queries;
    }

    /** 차량 로스터. 프론트가 SSE 를 열기 전에 차량 메타를 심는다. */
    @GetMapping("/vehicles")
    public Map<String, Object> vehicles() {
        return Map.of("vehicles", queries.vehicles());
    }

    /** 클립 카탈로그. 검색 결과의 재생 진입점이다. */
    @GetMapping("/clips")
    public List<Map<String, Object>> clips(@RequestParam(defaultValue = "100") int limit) {
        return queries.clips(Math.min(limit, 1000));
    }

    /**
     * 파이프라인 건강도.
     *
     * <p>{@code total_missing} 이 0 이 아니면 <b>유실이 있다</b> — 결번이 곧 유실이다.
     */
    @GetMapping("/health")
    public Map<String, Object> health() {
        return queries.health();
    }
}
