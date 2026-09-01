#!/usr/bin/env bash
# FleetSentinel — 개발용 사설 PKI.
#
# 공개 CA를 쓸 수 없다. 공개 CA는 도메인 소유권만 검증할 수 있어 `vehicle-0042` 같은
# 이름을 발급해주지 않는다. 검증하는 쪽이 게이트웨이 하나뿐이므로 자체 CA로 충분하고,
# 그래야 vehicle_id를 인증서에 박아 넣을 수 있다 (SDD S-11).
#
# ⚠️ 개발용이다. 제조 시점 프로비저닝(TPM·secure element), 로테이션, 폐기(CRL/OCSP)는
#    없다 — SDD L-7. 여기서 나온 키는 평문 파일이다.
#
# 사용:
#   scripts/gen-certs.sh                      # 서버 + vehicle-0001,0002
#   scripts/gen-certs.sh v001 v002 v003       # 차량 ID 직접 지정
#   PKI_DIR=/tmp/pki scripts/gen-certs.sh
set -euo pipefail

PKI_DIR="${PKI_DIR:-./pki}"
DAYS="${DAYS:-825}"
SERVER_DNS="${SERVER_DNS:-localhost}"
TRUST_DOMAIN="spiffe://fleetsentinel"

VEHICLES=("$@")
if [ ${#VEHICLES[@]} -eq 0 ]; then
  VEHICLES=(vehicle-0001 vehicle-0002)
fi

mkdir -p "$PKI_DIR"/{ca,server,vehicles}

# ── 루트 CA ──────────────────────────────────────────────────────────────
if [ -f "$PKI_DIR/ca/ca.crt" ]; then
  echo "  = CA 재사용: $PKI_DIR/ca/ca.crt"
else
  openssl req -x509 -newkey rsa:4096 -sha256 -days $((DAYS * 4)) -nodes \
    -keyout "$PKI_DIR/ca/ca.key" -out "$PKI_DIR/ca/ca.crt" \
    -subj "/O=FleetSentinel/CN=FleetSentinel Dev Root CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
  chmod 600 "$PKI_DIR/ca/ca.key"
  echo "  + CA 생성: $PKI_DIR/ca/ca.crt"
fi

# ── 서버 인증서 ──────────────────────────────────────────────────────────
# 차량도 "내가 붙은 게 진짜 게이트웨이인가"를 검증해야 한다. 이쪽은 접속 대상이라
# 호스트명이 있고, 그래서 SAN이 DNS다 — 클라이언트 인증서와 대조적이다.
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout "$PKI_DIR/server/server.key" -out "$PKI_DIR/server/server.csr" \
  -subj "/O=FleetSentinel/CN=${SERVER_DNS}" 2>/dev/null

openssl x509 -req -in "$PKI_DIR/server/server.csr" -days "$DAYS" -sha256 \
  -CA "$PKI_DIR/ca/ca.crt" -CAkey "$PKI_DIR/ca/ca.key" -CAcreateserial \
  -out "$PKI_DIR/server/server.crt" \
  -extfile <(printf '%s\n' \
      "basicConstraints=critical,CA:FALSE" \
      "keyUsage=critical,digitalSignature,keyEncipherment" \
      "extendedKeyUsage=serverAuth" \
      "subjectAltName=DNS:${SERVER_DNS},DNS:gateway,IP:127.0.0.1") 2>/dev/null

chmod 600 "$PKI_DIR/server/server.key"
rm -f "$PKI_DIR/server/server.csr"
echo "  + 서버 인증서: CN=${SERVER_DNS}"

# ── 차량 인증서 ──────────────────────────────────────────────────────────
# 신원은 SAN URI에 들어간다. CN이 아니다 — CN 기반 신원은 웹 PKI에서 폐기됐고,
# 자유 문자열이라 규약을 강제하기 어렵다. 게이트웨이는 SAN URI만 본다.
for v in "${VEHICLES[@]}"; do
  d="$PKI_DIR/vehicles/$v"
  mkdir -p "$d"

  openssl req -newkey rsa:2048 -sha256 -nodes \
    -keyout "$d/$v.key" -out "$d/$v.csr" \
    -subj "/O=FleetSentinel/OU=fleet/CN=${v}" 2>/dev/null

  openssl x509 -req -in "$d/$v.csr" -days "$DAYS" -sha256 \
    -CA "$PKI_DIR/ca/ca.crt" -CAkey "$PKI_DIR/ca/ca.key" -CAcreateserial \
    -out "$d/$v.crt" \
    -extfile <(printf '%s\n' \
        "basicConstraints=critical,CA:FALSE" \
        "keyUsage=critical,digitalSignature,keyEncipherment" \
        "extendedKeyUsage=clientAuth" \
        "subjectAltName=URI:${TRUST_DOMAIN}/vehicle/${v}") 2>/dev/null

  chmod 600 "$d/$v.key"
  rm -f "$d/$v.csr"
  echo "  + 차량 인증서: ${TRUST_DOMAIN}/vehicle/${v}"
done

# ── 사칭 테스트용 ────────────────────────────────────────────────────────
# 유효한 CA 서명을 받았지만 SAN이 vehicle-0001인 인증서. 이걸로 x-vehicle-id를
# vehicle-0002라고 주장하면 게이트웨이가 PERMISSION_DENIED로 끊어야 한다.
# "인증서가 유효하면 통과"와 "신원이 일치해야 통과"의 차이를 실제로 확인하는 자리다.
if [ ! -f "$PKI_DIR/vehicles/vehicle-0001/vehicle-0001.crt" ]; then
  echo "  ! 사칭 테스트 인증서는 vehicle-0001이 있을 때만 만든다"
else
  echo "  = 사칭 테스트: vehicle-0001 인증서로 x-vehicle-id=vehicle-0002 주장"
fi

echo
echo "PKI 준비 완료 → $PKI_DIR"
echo "  게이트웨이:  FLEETSENTINEL_PKI=$PKI_DIR"
echo "  검증:        openssl x509 -in $PKI_DIR/vehicles/${VEHICLES[0]}/${VEHICLES[0]}.crt -noout -text | grep -A1 'Alternative Name'"
