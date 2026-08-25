#!/usr/bin/env bash
# FleetSentinel — G001 스모크 테스트 (수용 기준).
# 전 서비스 healthy + 토픽 존재 + ClickHouse 질의 + MinIO 버킷 + Iceberg REST + Flink.
# compose up 이전에는 실패(빨간불), up 이후 통과(초록불)해야 한다. TDD 게이트.
set -uo pipefail

COMPOSE="${COMPOSE:-docker compose -f infra/docker-compose.yml}"
FAIL=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=1; }

echo "== 1. container health =="
for svc in kafka1 kafka2 kafka3 minio iceberg-rest jobmanager taskmanager clickhouse; do
  cid=$($COMPOSE ps -q "$svc" 2>/dev/null)
  if [ -z "$cid" ]; then bad "$svc not running"; continue; fi
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null)
  case "$health" in
    healthy|running) ok "$svc ($health)";;
    *) bad "$svc unhealthy ($health)";;
  esac
done

echo "== 2. kafka topics (RF=3) =="
topics=$($COMPOSE exec -T kafka1 sh -c "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list" 2>/dev/null || true)
for t in telemetry.raw telemetry.dlq; do
  if echo "$topics" | grep -qx "$t"; then
    desc=$($COMPOSE exec -T kafka1 sh -c "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic $t" 2>/dev/null)
    rf=$(echo "$desc" | grep -o 'ReplicationFactor: [0-9]*' | head -1 | awk '{print $2}')
    [ "$rf" = "3" ] && ok "topic $t (RF=$rf)" || bad "topic $t RF=$rf (expected 3)"
    echo "$desc" | grep -q 'min.insync.replicas=2' && ok "topic $t (min.insync.replicas=2, ADR-009)" || bad "topic $t missing min.insync.replicas=2"
  else
    bad "topic $t missing"
  fi
done

echo "== 3. clickhouse =="
CH="http://localhost:8124/?user=fleet&password=fleet"
ch_ver=$(curl -sf "$CH" --data "SELECT version()" 2>/dev/null)
[ -n "$ch_ver" ] && ok "ClickHouse 질의 응답 (v$ch_ver)" || bad "ClickHouse 질의 실패"
ch_db=$(curl -sf "$CH" --data "SELECT count() FROM system.databases WHERE name='fleet'" 2>/dev/null)
[ "$ch_db" = "1" ] && ok "fleet 데이터베이스 존재" || bad "fleet 데이터베이스 없음"
# 지리 함수 — Elasticsearch를 대체할 수 있는지의 근거(docs/sdd.md §4.1 A-8)
ch_geo=$(curl -sf "$CH" --data "SELECT pointInPolygon((1.5,1.5),[(0.,0.),(3.,0.),(3.,3.),(0.,3.)])" 2>/dev/null)
[ "$ch_geo" = "1" ] && ok "지리 함수 동작 (pointInPolygon)" || bad "지리 함수 실패"

echo "== 5. minio buckets =="
buckets=$($COMPOSE exec -T minio sh -c "mc alias set l http://localhost:9000 admin password >/dev/null 2>&1; mc ls l 2>/dev/null" || true)
for b in warehouse checkpoints; do
  echo "$buckets" | grep -q "$b" && ok "bucket $b" || bad "bucket $b missing"
done

echo "== 6. iceberg REST catalog =="
curl -sf "http://localhost:8181/v1/config?warehouse=s3://warehouse/" >/dev/null 2>&1 && ok "iceberg-rest /v1/config" || bad "iceberg-rest unreachable"

echo "== 7. flink jobmanager =="
ov=$(curl -sf "http://localhost:8081/overview" 2>/dev/null)
[ -n "$ov" ] && ok "flink REST /overview" || bad "flink JM unreachable"
tm=$(echo "$ov" | grep -o '"taskmanagers":[0-9]*' | head -1 | cut -d: -f2)
if [ "${tm:-0}" -ge 1 ] 2>/dev/null; then ok "flink taskmanagers=$tm (>=1 registered)"; else bad "flink taskmanagers=${tm:-0} (no TM registered)"; fi

echo
if [ "$FAIL" -eq 0 ]; then printf '\033[32m== SMOKE OK ==\033[0m\n'; else printf '\033[31m== SMOKE FAILED ==\033[0m\n'; fi
exit $FAIL
