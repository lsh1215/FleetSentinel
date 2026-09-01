#!/usr/bin/env python3
"""Kafka에 실제로 적재된 것을 꺼내 Avro로 디코딩하고 계약과 대조한다.

게이트웨이가 "보냈다"고 말하는 것과 **저장 계층이 실제로 받은 것**은 다른 주장이다.
이 스크립트는 후자만 본다 — 토픽에서 직접 읽어 `schemas/*.avsc` 로 디코딩하고,
결번·채널 분포·헤더 정합을 확인한다.

사용:
    PYTHONPATH=. .venv/bin/python scripts/verify_kafka.py --boot-id <boot_id>
    ... --brokers localhost:29092 --expect-signals 51025 --expect-perception 6789
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import sys
from pathlib import Path

import fastavro
from confluent_kafka import Consumer, TopicPartition

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _headers(msg) -> dict:
    return {k: (v.decode() if isinstance(v, (bytes, bytearray)) else v)
            for k, v in (msg.headers() or [])}


def drain(brokers: str, topic: str, boot_id: str | None, timeout_s: float = 20.0):
    """토픽을 처음부터 끝까지 읽는다. `boot_id`를 주면 그 스트림만 남긴다."""
    c = Consumer({
        "bootstrap.servers": brokers,
        "group.id": f"verify-{topic}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    md = c.list_topics(topic, timeout=10)
    parts = list(md.topics[topic].partitions)
    c.assign([TopicPartition(topic, p, 0) for p in parts])

    highs = {}
    for p in parts:
        _, hi = c.get_watermark_offsets(TopicPartition(topic, p), timeout=10)
        highs[p] = hi
    remaining = sum(highs.values())

    out = []
    read = 0
    while read < remaining:
        msg = c.poll(timeout_s)
        if msg is None:
            break
        if msg.error():
            continue
        read += 1
        h = _headers(msg)
        if boot_id and h.get("boot_id") != boot_id:
            continue
        out.append((msg, h))
    c.close()
    return out, remaining


def check_gaps(seqs: list[int]) -> dict:
    """결번 검사. `seq`는 차량별 단조 증가이므로 구멍이 곧 유실이다."""
    if not seqs:
        return {"n": 0}
    s = sorted(seqs)
    expected = set(range(s[0], s[-1] + 1))
    missing = sorted(expected - set(s))
    dupes = len(s) - len(set(s))
    return {
        "n": len(s), "min": s[0], "max": s[-1],
        "missing_n": len(missing), "missing_sample": missing[:10],
        "duplicate_n": dupes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brokers", default="localhost:29092")
    ap.add_argument("--topic", default="telemetry.records")
    ap.add_argument("--boot-id", default=None,
                    help="이 스트림만 검사한다. 생략하면 토픽 전체")
    ap.add_argument("--vehicle", default=None, help="기대하는 파티션 키")
    ap.add_argument("--expect-signals", type=int, default=None)
    ap.add_argument("--expect-perception", type=int, default=None)
    args = ap.parse_args()

    sig_schema = fastavro.parse_schema(
        json.loads((SCHEMA_DIR / "vehicle-signal.avsc").read_text()))
    per_schema = fastavro.parse_schema(
        json.loads((SCHEMA_DIR / "perception-object.avsc").read_text()))

    failures: list[str] = []

    # ── 단일 토픽에서 kind 로 갈라 본다 ──────────────────────────────────
    # 계층별 토픽을 쓰면 `seq` 단일 수열이 조각나 dedup 이 깨진다(create-topics.sh 주석).
    all_msgs, total = drain(args.brokers, args.topic, args.boot_id)
    by_kind = collections.defaultdict(list)
    for msg, h in all_msgs:
        by_kind[h.get("kind", "?")].append((msg, h))

    msgs = by_kind.get("RECORD_KIND_SIGNAL", [])
    print(f"═══ {args.topic} ═══  전체 {total:,}건 중 이 스트림 {len(all_msgs):,}건")
    print(f"  kind 분포: " + " · ".join(f"{k}={len(v):,}" for k, v in sorted(by_kind.items())))
    print(f"\n── 신호 {len(msgs):,}건 ──")

    channels = collections.Counter()
    seqs, keys, parts = [], set(), set()
    decode_fail = 0
    num_keys, vec_keys, str_keys = set(), set(), set()
    for msg, h in msgs:
        try:
            rec = fastavro.schemaless_reader(io.BytesIO(msg.value()), sig_schema)
        except Exception as e:  # noqa: BLE001
            decode_fail += 1
            if decode_fail == 1:
                print(f"  ⚠️ 디코딩 실패 예시: {e!r}")
            continue
        channels[rec["channel"]] += 1
        seqs.append(int(h["seq"]))
        keys.add(msg.key().decode())
        parts.add(msg.partition())
        num_keys.update(rec["values_num"]); vec_keys.update(rec["values_vec"])
        str_keys.update(rec["values_str"])
        if rec["log_time"] != rec["sensor_time"]:
            failures.append("재생기는 log_time == sensor_time 이어야 한다")

    print(f"  Avro 디코딩 실패 {decode_fail}건")
    if decode_fail:
        failures.append(f"신호 Avro 디코딩 실패 {decode_fail}건")

    g = check_gaps(seqs)
    print(f"  seq {g.get('min')}~{g.get('max')} · 결번 {g.get('missing_n')}건 · "
          f"중복 {g.get('duplicate_n')}건")
    if g.get("missing_n"):
        failures.append(f"신호 seq 결번 {g['missing_n']}건 {g['missing_sample']}")
    if g.get("duplicate_n"):
        failures.append(f"신호 seq 중복 {g['duplicate_n']}건")

    print(f"  파티션 {sorted(parts)} · 키 {sorted(keys)}")
    if len(parts) > 1:
        failures.append(f"한 차량이 여러 파티션에 걸쳤다 {sorted(parts)} — CACK 전제 위반(A-L5)")
    if args.vehicle and keys != {args.vehicle}:
        failures.append(f"파티션 키가 인증서 신원과 다르다: {keys}")

    print(f"  채널 분포:")
    for ch, n in channels.most_common():
        print(f"    {ch:<22} {n:>8,} ({n/max(len(seqs),1)*100:>5.1f}%)")
    print(f"  values 키: num {len(num_keys)}종 · vec {len(vec_keys)}종 · str {len(str_keys)}종")

    if args.expect_signals is not None and len(seqs) != args.expect_signals:
        failures.append(f"신호 건수 {len(seqs):,} ≠ 기대 {args.expect_signals:,}")

    # 채널 네이티브인지: ego_pose 만 있으면 결합형이다
    if len(channels) <= 1:
        failures.append("채널이 1종뿐이다 — 결합형(SignalRecord)을 보내고 있다")

    # ── 인지 ────────────────────────────────────────────────────────────
    msgs = by_kind.get("RECORD_KIND_PERCEPTION", [])
    print(f"\n── 인지 {len(msgs):,}건 ──")
    cats = collections.Counter()
    vis = collections.Counter()
    pseqs = []
    decode_fail = 0
    lidar_zero = 0
    for msg, h in msgs:
        try:
            rec = fastavro.schemaless_reader(io.BytesIO(msg.value()), per_schema)
        except Exception:  # noqa: BLE001
            decode_fail += 1
            continue
        cats[rec["category"]] += 1
        vis[rec["visibility"]] += 1
        pseqs.append(int(h["seq"]))
        if rec["num_lidar_pts"] == 0:
            lidar_zero += 1

    print(f"  Avro 디코딩 실패 {decode_fail}건")
    if decode_fail:
        failures.append(f"인지 Avro 디코딩 실패 {decode_fail}건")
    if pseqs:
        print(f"  seq {min(pseqs)}~{max(pseqs)}")
        print(f"  카테고리 {len(cats)}종 · 상위: "
              + ", ".join(f"{c}({n})" for c, n in cats.most_common(3)))
        print(f"  LiDAR 0포인트 {lidar_zero:,}/{len(pseqs):,} = "
              f"{lidar_zero/len(pseqs)*100:.1f}%  (데이터 설계 §8.1 기대 23.1%)")
    if args.expect_perception is not None and len(pseqs) != args.expect_perception:
        failures.append(f"인지 건수 {len(pseqs):,} ≠ 기대 {args.expect_perception:,}")

    # ── 신호+인지 seq 가 한 시퀀스인지 ──────────────────────────────────
    allseq = check_gaps(seqs + pseqs)
    print(f"\n═══ 통합 seq ═══  {allseq.get('min')}~{allseq.get('max')} · "
          f"{allseq.get('n'):,}건 · 결번 {allseq.get('missing_n')}건 · "
          f"중복 {allseq.get('duplicate_n')}건")
    if allseq.get("missing_n"):
        failures.append(f"통합 seq 결번 {allseq['missing_n']}건 — 유실이다")

    print()
    if failures:
        print("❌ 실패")
        for f in failures:
            print(f"   · {f}")
        return 1
    print("✅ Kafka 적재분이 계약과 일치한다 — 결번 0 · 중복 0 · Avro 디코딩 전량 성공")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
