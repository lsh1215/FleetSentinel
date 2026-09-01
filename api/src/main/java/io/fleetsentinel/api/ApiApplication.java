package io.fleetsentinel.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * FleetSentinel 관제 API.
 *
 * <p>대시보드가 목업 스트림 대신 이걸 본다. 계약은 프론트엔드가 이미 쓰고 있는 네 경로다 —
 * {@code /api/vehicles} · {@code /api/stream} · {@code /api/clips} · {@code /api/health}.
 * <b>프론트를 고치지 않는 것이 목표</b>이므로 응답 형태를 목업과 같게 맞춘다.
 *
 * <h2>ClickHouse 를 어떻게 읽는가</h2>
 *
 * <p><b>{@code _raw} 테이블을 직접 읽지 않는다.</b> Flink→ClickHouse 는 at-least-once 라
 * 머지 전에는 중복이 보인다(SDD L-14). {@code FINAL} 이 박힌 뷰만 본다 —
 * {@code infra/clickhouse/001-schema.sql}.
 */
@SpringBootApplication
@EnableScheduling   // SSE 폴링 주기 작업에 필요하다
public class ApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(ApiApplication.class, args);
    }
}
