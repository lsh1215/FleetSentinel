package io.fleetsentinel.gateway;

import io.fleetsentinel.gateway.config.GatewayProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

/**
 * FleetSentinel 수집 게이트웨이.
 *
 * <p>차량 gRPC 업링크를 종단해 Kafka에 쓴다. <b>리버스 프록시가 아니다</b> — 라우팅할
 * 다운스트림이 없고, 핵심 작업(프로듀서 콜백 기반 CACK 산출, 인증서 신원 바인딩)이 라우트
 * 필터에 넣을 성질이 아니다. 근거는 SDD §4.1 A-14.
 */
@SpringBootApplication
@EnableConfigurationProperties(GatewayProperties.class)
public class GatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(GatewayApplication.class, args);
    }
}
