package io.fleetsentinel.gateway.config;

import java.net.URI;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

/**
 * S3 클라이언트 + presigner.
 *
 * <p><b>게이트웨이가 스토리지 자격증명을 갖는다.</b> 차량에서 걷어낸 문제를 여기로 옮긴
 * 것이므로(SDD L-7), 운영에서는 IAM 역할을
 * `PutObject` + 이 버킷 접두사로 최소화해야 한다. 로컬은 MinIO 루트 계정이다.
 */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(ObjectStoreProperties.class)
public class ObjectStoreConfig {

    private static StaticCredentialsProvider creds(ObjectStoreProperties p) {
        return StaticCredentialsProvider.create(
                AwsBasicCredentials.create(p.getAccessKey(), p.getSecretKey()));
    }

    @Bean(destroyMethod = "close")
    public S3Client s3Client(ObjectStoreProperties p) {
        var builder = S3Client.builder()
                .region(Region.of(p.getRegion()))
                .credentialsProvider(creds(p))
                // MinIO는 가상 호스트 스타일을 기본 지원하지 않는다.
                .serviceConfiguration(S3Configuration.builder()
                        .pathStyleAccessEnabled(p.isPathStyleAccess())
                        .build());
        if (p.getEndpoint() != null && !p.getEndpoint().isBlank()) {
            builder.endpointOverride(URI.create(p.getEndpoint()));
        }
        return builder.build();
    }

    @Bean(destroyMethod = "close")
    public S3Presigner s3Presigner(ObjectStoreProperties p) {
        var builder = S3Presigner.builder()
                .region(Region.of(p.getRegion()))
                .credentialsProvider(creds(p))
                .serviceConfiguration(S3Configuration.builder()
                        .pathStyleAccessEnabled(p.isPathStyleAccess())
                        .build());
        if (p.getEndpoint() != null && !p.getEndpoint().isBlank()) {
            builder.endpointOverride(URI.create(p.getEndpoint()));
        }
        return builder.build();
    }
}
