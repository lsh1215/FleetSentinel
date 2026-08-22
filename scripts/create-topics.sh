#!/usr/bin/env bash
# FleetSentinel — Kafka 토픽 부트스트랩 (ADR-009: RF=3 / min.insync.replicas=2)
# telemetry.raw : 수집 원본 (Avro)
# telemetry.dlq : 검증 실패 3종 격리 (§6.7)
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose -f infra/docker-compose.yml}"
KT="/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092"

create_topic() {
  local name="$1" parts="$2"
  if $COMPOSE exec -T kafka1 sh -c "$KT --describe --topic $name" >/dev/null 2>&1; then
    echo "  = topic exists: $name"
  else
    $COMPOSE exec -T kafka1 sh -c \
      "$KT --create --topic $name --partitions $parts --replication-factor 3 \
       --config min.insync.replicas=2 --config unclean.leader.election.enable=false"
    echo "  + created: $name (partitions=$parts, RF=3, min.isr=2)"
  fi
}

echo "== creating topics =="
create_topic telemetry.raw 3
create_topic telemetry.dlq 3

echo "== topic list =="
$COMPOSE exec -T kafka1 sh -c "$KT --list"
