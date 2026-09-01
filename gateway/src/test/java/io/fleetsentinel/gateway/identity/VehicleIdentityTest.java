package io.fleetsentinel.gateway.identity;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 신원 추출 계약. 여기가 뚫리면 유실 0 주장이 깨진다 — dedup이
 * {@code keyBy(vehicle_id) + seq} 윈도우라, 남의 vehicle_id로 seq를 밀면 그 차량의
 * 정상 레코드가 {@code too_old}로 버려진다(SDD S-11).
 *
 * <p>인증서는 BouncyCastle 없이 만들기 번거로우므로 {@code openssl}로 굽는다. 테스트가
 * openssl에 의존하지만, 실제 발급 경로({@code scripts/gen-certs.sh})와 같은 도구를 쓰므로
 * "테스트에서만 통하는 인증서"가 생기지 않는다는 이점이 있다.
 */
class VehicleIdentityTest {

    @Test
    @DisplayName("규약에 맞는 SAN URI에서 vehicle_id를 뽑는다")
    void extractsFromConformantSan() throws Exception {
        var cert = CertFixture.withSan("URI:spiffe://fleetsentinel/vehicle/vehicle-0042");

        var identity = VehicleIdentity.fromCertificate(cert);

        assertThat(identity).isPresent();
        assertThat(identity.get().vehicleId()).isEqualTo("vehicle-0042");
        assertThat(identity.get().spiffeId()).isEqualTo("spiffe://fleetsentinel/vehicle/vehicle-0042");
    }

    @Test
    @DisplayName("SAN이 없으면 신원 없음 — CN으로 되돌아가지 않는다")
    void noSanMeansNoIdentity() throws Exception {
        // CN=vehicle-0042 지만 SAN이 없다. CN은 자유 문자열이라 규약을 강제할 수 없어
        // 보지 않는다. 관대하게 넘기면 검사의 의미가 없어진다.
        var cert = CertFixture.withoutSan("/O=FleetSentinel/CN=vehicle-0042");

        assertThat(VehicleIdentity.fromCertificate(cert)).isEmpty();
    }

    @Test
    @DisplayName("다른 trust domain은 거절한다")
    void rejectsForeignTrustDomain() throws Exception {
        var cert = CertFixture.withSan("URI:spiffe://evil.example/vehicle/vehicle-0042");

        assertThat(VehicleIdentity.fromCertificate(cert)).isEmpty();
    }

    @Test
    @DisplayName("DNS SAN은 신원이 아니다")
    void dnsSanIsNotIdentity() throws Exception {
        var cert = CertFixture.withSan("DNS:vehicle-0042.fleetsentinel.example");

        assertThat(VehicleIdentity.fromCertificate(cert)).isEmpty();
    }

    @Test
    @DisplayName("경로를 벗어난 URI는 거절한다")
    void rejectsMalformedPath() throws Exception {
        for (String san : List.of(
                "URI:spiffe://fleetsentinel/vehicle/",           // ID 없음
                "URI:spiffe://fleetsentinel/gateway/g-01",       // vehicle 아님
                "URI:spiffe://fleetsentinel/vehicle/a/b",        // 경로가 더 깊다
                "URI:spiffe://fleetsentinel/vehicle/../admin")) { // 경로 탈출 시도
            var cert = CertFixture.withSan(san);
            assertThat(VehicleIdentity.fromCertificate(cert))
                    .as("거절해야 한다: %s", san)
                    .isEmpty();
        }
    }

    @Test
    @DisplayName("규약에 맞는 URI가 둘이면 거절한다 — 어느 쪽이 신원인지 정할 근거가 없다")
    void rejectsAmbiguousIdentity() throws Exception {
        var cert = CertFixture.withSan(
                "URI:spiffe://fleetsentinel/vehicle/vehicle-0001,"
                        + "URI:spiffe://fleetsentinel/vehicle/vehicle-0002");

        assertThat(VehicleIdentity.fromCertificate(cert)).isEmpty();
    }

    /** openssl로 자체 서명 인증서를 굽는다. 서명 유효성은 여기 관심사가 아니다 — SAN 파싱만 본다. */
    static final class CertFixture {

        static X509Certificate withSan(String san) throws Exception {
            return generate("/O=FleetSentinel/CN=test", "subjectAltName=" + san);
        }

        static X509Certificate withoutSan(String subject) throws Exception {
            return generate(subject, null);
        }

        private static X509Certificate generate(String subject, String sanExt) throws Exception {
            var dir = java.nio.file.Files.createTempDirectory("certfix");
            try {
                var key = dir.resolve("k.pem");
                var crt = dir.resolve("c.pem");

                var cmd = new java.util.ArrayList<>(List.of(
                        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                        "-days", "1", "-nodes",
                        "-keyout", key.toString(), "-out", crt.toString(),
                        "-subj", subject));
                if (sanExt != null) {
                    cmd.addAll(List.of("-addext", sanExt));
                }

                var proc = new ProcessBuilder(cmd)
                        .redirectErrorStream(true)
                        .start();
                String output = new String(proc.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
                int exit = proc.waitFor();
                if (exit != 0) {
                    throw new IllegalStateException("openssl 실패 (" + exit + "): " + output);
                }

                var factory = CertificateFactory.getInstance("X.509");
                try (var in = new ByteArrayInputStream(java.nio.file.Files.readAllBytes(crt))) {
                    return (X509Certificate) factory.generateCertificate(in);
                }
            } finally {
                try (var walk = java.nio.file.Files.walk(dir)) {
                    walk.sorted(java.util.Comparator.reverseOrder())
                            .forEach(p -> p.toFile().delete());
                }
            }
        }
    }
}
