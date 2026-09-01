package io.fleetsentinel.gateway.identity;

import java.security.cert.CertificateParsingException;
import java.security.cert.X509Certificate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * 차량 신원. <b>클라이언트 인증서에서만</b> 나온다.
 *
 * <p>차량이 메타데이터로 보낸 {@code x-vehicle-id}는 주장일 뿐이고, 이 클래스가 만든 값과
 * 대조해서 다르면 스트림을 거절한다(SDD S-11). 신원을 페이로드에서 읽으면 인증서 하나가
 * 털린 차량이 남의 {@code vehicle_id}로 쏠 수 있고, dedup이
 * {@code keyBy(vehicle_id) + seq} 슬라이딩 윈도우라 그 결과가 단순 오염이 아니라
 * <b>표적 유실</b>이 된다 — 남의 seq를 밀어 정상 레코드를 윈도우 밖으로 떨어뜨린다.
 *
 * @param vehicleId SAN URI에서 추출한 차량 ID
 * @param spiffeId  원본 SAN URI 전체. 로그·DLQ에 남긴다
 */
public record VehicleIdentity(String vehicleId, String spiffeId) {

    /** SAN 항목의 첫 원소가 URI임을 뜻하는 값. RFC 5280 GeneralName의 uniformResourceIdentifier. */
    private static final int SAN_TYPE_URI = 6;

    /**
     * 발급 규약. {@code spiffe://fleetsentinel/vehicle/{id}}.
     *
     * <p>SPIFFE 형식을 쓰는 이유는 표준을 따르려는 것보다도, DNS 이름이 아닌 신원을 담을
     * 자리가 X.509에 URI SAN밖에 마땅치 않기 때문이다. 공개 CA는 도메인 소유권만 검증할 수
     * 있어 {@code vehicle-0042} 같은 이름을 발급해주지 않는다 — 그래서 사설 CA다(L-7).
     */
    private static final Pattern SPIFFE_VEHICLE =
            Pattern.compile("^spiffe://fleetsentinel/vehicle/([A-Za-z0-9][A-Za-z0-9._-]{0,63})$");

    /**
     * 인증서에서 차량 신원을 뽑는다.
     *
     * <p><b>CN은 보지 않는다.</b> CN 기반 신원은 웹 PKI에서 폐기됐고, 무엇보다 자유 문자열이라
     * 규약을 강제하기 어렵다. SAN URI가 규약에 맞지 않으면 신원 없음으로 처리한다 —
     * 관대하게 넘기면 검사의 의미가 없어진다.
     *
     * @return 규약에 맞는 SAN URI가 정확히 하나 있을 때만 신원, 아니면 비어 있음
     */
    public static Optional<VehicleIdentity> fromCertificate(X509Certificate cert) {
        Collection<List<?>> sans;
        try {
            sans = cert.getSubjectAlternativeNames();
        } catch (CertificateParsingException e) {
            return Optional.empty();
        }
        if (sans == null) {
            return Optional.empty();
        }

        VehicleIdentity found = null;
        for (List<?> san : sans) {
            if (san.size() < 2 || !(san.get(0) instanceof Integer type) || type != SAN_TYPE_URI) {
                continue;
            }
            if (!(san.get(1) instanceof String uri)) {
                continue;
            }
            var m = SPIFFE_VEHICLE.matcher(uri);
            if (!m.matches()) {
                continue;
            }
            if (found != null) {
                // 규약에 맞는 URI가 둘 이상이면 어느 쪽이 신원인지 정할 근거가 없다.
                // 발급 실수이므로 통과시키지 않는다.
                return Optional.empty();
            }
            found = new VehicleIdentity(m.group(1), uri);
        }
        return Optional.ofNullable(found);
    }
}
