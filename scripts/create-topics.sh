#!/usr/bin/env bash
# FleetSentinel — Kafka 토픽 부트스트랩 (ADR-009: RF=3 / min.insync.replicas=2)
# **토픽은 하나다.** 계층(신호·인지·참조)을 토픽으로 나누면 `seq` 단일 수열이 쪼개진다.
#
# `seq`는 차량별로 하나뿐이고(WAL이 발급, data-design.md §5.0) 결번이 곧 유실이다.
# 계층별로 토픽을 나누면 그 수열이 토픽마다 조각나서
#   ① Kafka는 파티션 안에서만 순서를 보장하므로 dedup 이 연속성을 볼 수 없고
#   ② 각 토픽만 보면 남의 계층 구간이 전부 결번으로 보여 유실 탐지가 거짓 양성을 낸다
# 실제로 계층 분리 상태에서 신호 51,025건이 전부 `too_old` 로 폐기됐다.
#
# 계층 분기는 **Flink 이후**(ClickHouse 테이블)에서 한다. `kind` 헤더가 구분자다.
#
# telemetry.records : ①②③ 전부. 파티션 키 = vehicle_id, 계층은 kind 헤더
# telemetry.dlq     : 검증 실패 격리 (dlq-envelope.avsc)
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
create_topic telemetry.records 3
create_topic telemetry.dlq 3

echo "== topic list =="
$COMPOSE exec -T kafka1 sh -c "$KT --list"
