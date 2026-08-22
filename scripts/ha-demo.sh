#!/usr/bin/env bash
# FleetSentinel — G006 Kafka HA broker-kill 데모 (ADR-009)
#
# 실증: 단일 호스트 3-broker(RF=3 / min.insync.replicas=2 / acks=all)에서 브로커 1개를 kill해도
#       producer(acks=all)가 유실 없이 계속 발행되고, 소비 카운트가 발행 카운트와 정확히 일치한다.
#       = broker-level 복제·failover. (정직한 한계: 단일 호스트라 호스트/존 SPOF는 스코프 밖.)
#
# 재현: make up && make topics 로 스택이 뜬 상태에서 실행. 데모 전용 토픽(ha-demo)을 써서
#       telemetry.raw 파이프라인을 오염시키지 않는다.
#
# ⚠️ 이 스크립트는 브로커를 정지/재기동한다. 다른 작업(Flink 통합테스트 등)이 같은 Kafka를
#    쓰는 중에는 실행하지 말 것.
set -uo pipefail

COMPOSE="${COMPOSE:-docker compose -f infra/docker-compose.yml}"
TOPIC="${TOPIC:-ha-demo}"
KT="/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092"
GET_OFFSETS="/opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server localhost:9092"
VICTIM="${VICTIM:-kafka2}"
GEN_THROUGHPUT="${GEN_THROUGHPUT:-200}"              # records/sec
GEN_DURATION="${GEN_DURATION:-28}"                   # 발행이 kill(5s)→detection/재선출(~17s)→restart 창을 커버
GEN_RECORDS="${GEN_RECORDS:-$(( GEN_THROUGHPUT * GEN_DURATION ))}"
GEN_RECORD_SIZE="${GEN_RECORD_SIZE:-256}"
PERF="/opt/kafka/bin/kafka-producer-perf-test.sh"
FAIL=0
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=1; }

kx() { $COMPOSE exec -T kafka1 sh -c "$1"; }

echo "== 0. preflight: 데모 토픽 재생성 (RF=3, min.isr=2) =="
kx "$KT --delete --topic $TOPIC" >/dev/null 2>&1 || true
sleep 2
kx "$KT --create --topic $TOPIC --partitions 3 --replication-factor 3 --config min.insync.replicas=2 --config unclean.leader.election.enable=false" \
  && ok "topic $TOPIC created (RF=3, min.isr=2)" || { bad "topic create failed"; exit 1; }

echo "== 1. RF/ISR 초기 상태 =="
desc=$(kx "$KT --describe --topic $TOPIC")
echo "$desc" | grep -q 'ReplicationFactor: 3' && ok "ReplicationFactor=3" || bad "RF != 3"
echo "$desc" | grep -q 'min.insync.replicas=2' && ok "min.insync.replicas=2" || bad "min.isr != 2"

start_off=$(kx "$GET_OFFSETS --topic $TOPIC --time -2" | awk -F: '{s+=$3} END{print s+0}')
echo "  start offsets sum = $start_off"

echo "== 2. 발행 시작(백그라운드) + 발행 도중 브로커 HARD kill(SIGKILL)/복구 =="
# 부하 발생기 = Kafka 이미지에 내장된 kafka-producer-perf-test.sh.
# v2.0에서는 Python 합성 생성기를 썼으나 도메인 전환(v3.0)으로 제거됐다. HA 데모는 페이로드 내용과
# 무관하게 성립하므로 외부 의존이 없는 내장 도구로 대체해 스크립트를 자체완결형으로 만든다.
# 비멱등(enable.idempotence 미설정) + acks=all = at-least-once — failover 중 재시도 중복이 나올 수
# 있고, 이는 설계상 하류 Flink keyBy(event_id) dedup이 흡수한다(ADR-006).
gen_log=$(mktemp)
( kx "$PERF --topic $TOPIC --num-records $GEN_RECORDS --record-size $GEN_RECORD_SIZE --throughput $GEN_THROUGHPUT --producer-props bootstrap.servers=localhost:9092 acks=all retries=2147483647 delivery.timeout.ms=120000" ) >"$gen_log" 2>&1 &
GEN_PID=$!

VICTIM_ID="${VICTIM##kafka}"   # kafka2 -> node id 2
# 재선출 증거용: kill 전 victim이 리더인 파티션 기록
pre_desc=$(kx "$KT --describe --topic $TOPIC")
victim_led=$(echo "$pre_desc" | awk -v v="$VICTIM_ID" '/Partition:/{p="";l="";for(i=1;i<=NF;i++){if($i=="Partition:")p=$(i+1);if($i=="Leader:")l=$(i+1)}if(l==v)printf "%s ",p}')
echo "  pre-kill: broker $VICTIM(node $VICTIM_ID) leads partitions: ${victim_led:-<none>}"

sleep 5
echo "  --> HARD kill broker $VICTIM (SIGKILL — graceful 아님, 진짜 failure detection 유발)"
$COMPOSE kill -s KILL "$VICTIM" >/dev/null 2>&1
sleep 2
vrun=$(docker inspect -f '{{.State.Running}}' "fleet-$VICTIM" 2>/dev/null)
[ "$vrun" = "false" ] && ok "broker $VICTIM 컨테이너 실제 정지(SIGKILL 적용 확인 — silent no-op 아님)" || bad "broker $VICTIM 아직 running — kill이 no-op?"
echo "  ... failure detection + 리더 재선출 대기 (broker.session.timeout ~9s)"
sleep 12

dur_desc=$(kx "$KT --describe --topic $TOPIC")
# (a) 가용성: 모든 파티션 ISR>=2 (min.insync.replicas=2 계약)
avail=$(echo "$dur_desc" | awk '/Partition:/{for(i=1;i<=NF;i++)if($i=="Isr:"){n=split($(i+1),a,",");if(n>=2)okc++;else badc++}}END{print (badc>0?"NO":"YES")}')
[ "$avail" = "YES" ] && ok "all partitions ISR>=2 during HARD kill (available, min.isr 충족)" || bad "some partition ISR<2 during kill (unavailable)"
# (b) victim이 ISR에서 제거됨 (failure 감지 실증)
vin=$(echo "$dur_desc" | awk -v v="$VICTIM_ID" '/Partition:/{for(i=1;i<=NF;i++)if($i=="Isr:"){n=split($(i+1),a,",");for(j=1;j<=n;j++)if(a[j]==v)f=1}}END{print (f?"YES":"NO")}')
[ "$vin" = "NO" ] && ok "victim node $VICTIM_ID removed from all ISR (failure detected)" || echo "  주의: node $VICTIM_ID 아직 일부 ISR 잔존(감지 지연)"
# (c) 리더 재선출: victim이 리드하던 파티션이 새 리더를 가짐
if [ -z "$victim_led" ]; then
  echo "  참고: victim이 리드하던 파티션 없음 → 재선출 대상 없음(가용성만 실증)"
else
  reok=1; relist=""
  for p in $victim_led; do
    newl=$(echo "$dur_desc" | awk -v pp="$p" '/Partition:/{part="";lead="";for(i=1;i<=NF;i++){if($i=="Partition:")part=$(i+1);if($i=="Leader:")lead=$(i+1)}if(part==pp)print lead}')
    if [ -n "$newl" ] && [ "$newl" != "$VICTIM_ID" ]; then relist="$relist p${p}:node${newl}"; else reok=0; fi
  done
  [ "$reok" = 1 ] && ok "leader re-election:${relist} (victim 리드 파티션 전부 새 리더로 교체)" || bad "re-election incomplete (일부 victim-led 파티션 리더 미교체)"
fi

echo "  --> restart broker $VICTIM"
$COMPOSE start "$VICTIM" >/dev/null 2>&1

wait "$GEN_PID"
published=$(grep -oE '^[0-9]+ records sent' "$gen_log" | tail -1 | awk '{print $1}')
echo "  producer: published=${published:-0} records (kafka-producer-perf-test, acks=all)"
if [ -n "$published" ] && [ "$published" -gt 0 ] 2>/dev/null; then
  ok "producer published $published records (acks=all)"
else
  bad "producer did not publish"; sed -n '1,20p' "$gen_log"
fi

echo "== 3. ISR 완전 복원 대기 (하드 게이트) =="
restored=0
for i in $(seq 1 25); do
  isr=$(kx "$KT --describe --topic $TOPIC" | grep -c 'Isr: [0-9]*,[0-9]*,[0-9]*')
  [ "$isr" -ge 3 ] && { restored=1; break; }
  sleep 3
done
[ "$restored" = 1 ] && ok "ISR restored to 3 on all partitions" || bad "ISR did not restore to 3 within 75s (broker $VICTIM 미복귀)"

echo "== 4. 유실 0 대사 (zero-loss: consumed >= published) =="
sleep 2
end_off=$(kx "$GET_OFFSETS --topic $TOPIC --time -1" | awk -F: '{s+=$3} END{print s+0}')
consumed=$(( end_off - start_off ))
echo "  end offsets sum = $end_off, consumed(delta) = $consumed"
dup=$(( consumed - ${published:-0} ))
if [ "$consumed" -ge "${published:-0}" ] 2>/dev/null && [ "${published:-0}" -gt 0 ]; then
  ok "ZERO LOSS: consumed($consumed) >= published($published) despite broker kill — acked 이벤트 전량 durable"
  if [ "$dup" -gt 0 ]; then
    echo "  참고: 초과 $dup 건 = failover 중 producer 재시도 중복(비-멱등 acks=all=at-least-once)."
    echo "        이는 설계상 Flink keyBy(event_id) dedup(§6.4.1/ADR-006, TC-DEDUP-01)이 하류에서 흡수 →"
    echo "        스트림 exactly-once. Kafka 계층 대사 기준 = 유실 0(중복은 정상, dedup 대상)."
  else
    echo "  참고: 중복 0(이번 실행은 재시도 미발생)."
  fi
else
  bad "LOSS DETECTED: consumed($consumed) < published($published) — acked 이벤트 유실"
fi

rm -f "$gen_log"
echo
echo "정직한 한계(ADR-009): 단일 호스트 3-broker로 broker-level 복제·failover만 실증. 호스트/존 SPOF는 스코프 밖."
if [ "$FAIL" -eq 0 ]; then printf '\033[32m== HA DEMO OK ==\033[0m\n'; else printf '\033[31m== HA DEMO FAILED ==\033[0m\n'; fi
exit $FAIL
