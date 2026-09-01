package io.fleetsentinel.gateway.config;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * CACK 주기 플러시용 스케줄러.
 *
 * <p><b>왜 필요한가</b> — {@code AckTracker.take()}의 시간 조건은 호출될 때만 평가된다.
 * 그런데 호출 지점이 Kafka publish 완료 콜백 하나뿐이라, 차량이 {@code every-n}보다 적게
 * 보내고 조용해지면 <b>그 버스트에 대한 CACK이 영영 나가지 않는다.</b> 차량은 그만큼을
 * 커밋하지 못한 채 WAL에 들고 있게 된다 — 정차 중인 차량에서 정확히 그 일이 벌어진다.
 *
 * <p>주기 태스크가 그 조건을 대신 깨운다. 태스크 자체는 락을 잡고 `take()` 한 번 부르는
 * 것이 전부라 스트림 수가 늘어도 부담이 되지 않는다.
 */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(GatewayProperties.class)
public class AckSchedulerConfig {

    /**
     * 데몬 스레드로 둔다 — 종료를 막지 않아야 한다. 태스크가 짧아 스레드가 많을 이유가 없다.
     */
    @Bean(destroyMethod = "shutdownNow")
    public ScheduledExecutorService ackFlushScheduler() {
        ThreadFactory factory = new ThreadFactory() {
            private final AtomicInteger n = new AtomicInteger();

            @Override
            public Thread newThread(Runnable r) {
                Thread t = new Thread(r, "cack-flush-" + n.incrementAndGet());
                t.setDaemon(true);
                return t;
            }
        };
        return Executors.newScheduledThreadPool(2, factory);
    }
}
