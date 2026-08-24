#!/usr/bin/env python3
"""생성한 MCAP이 유효한지 되읽어 검증한다 (P1 게이트).

확인 항목:
  1. 파일 매직/요약(summary) 정상 — 인덱스가 기록됐는가
  2. 채널·스키마가 self-describing 하게 내장됐는가
  3. 메시지 수가 변환 매니페스트와 일치하는가
  4. 시간 범위로 **구간 랜덤 액세스**가 되는가 (MCAP 인덱스의 존재 이유)
  5. 원시 센서 페이로드가 실제 바이트인가 (JPEG 매직 등)
  6. **무손실 계약** — 장면에 속한 sample_data 전량이 담겼는가 (SDD L-10 회귀 방지)

6번은 `--dataroot`를 주면 실행된다. nuScenes DB에서 "장면에 속한 sample_data"의
정본 정의(sample_token이 장면의 sample에 속하는 전체)를 뽑아 MCAP 메시지 수와 대조한다.
키프레임만 담던 결함이 되살아나면 여기서 잡힌다.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from mcap.reader import make_reader

FAIL = 0


def ok(msg: str) -> None:
    print(f"  \033[32mPASS\033[0m {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL = 1
    print(f"  \033[31mFAIL\033[0m {msg}")


def canonical_raw_counts(dataroot: Path, version: str = "v1.0-mini") -> dict:
    """nuScenes DB에서 장면별 정본 sample_data 수를 구한다."""
    from nuscenes.nuscenes import NuScenes

    nusc = NuScenes(version=version, dataroot=str(dataroot), verbose=False)
    out = {}
    for scene in nusc.scene:
        tokens, tok = set(), scene["first_sample_token"]
        while tok:
            tokens.add(tok)
            tok = nusc.get("sample", tok)["next"]
        sds = [sd for sd in nusc.sample_data if sd["sample_token"] in tokens]
        out[scene["name"]] = {
            "total": len(sds),
            "keyframe": sum(1 for sd in sds if sd["is_key_frame"]),
            "sweep": sum(1 for sd in sds if not sd["is_key_frame"]),
        }
    return out


def main() -> int:
    out_dir = Path(sys.argv[1])
    dataroot = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    manifest = json.loads((out_dir / "manifest.json").read_text())

    canonical = {}
    if dataroot:
        print("정본 sample_data 수 계산 중 (무손실 계약 검사)...")
        canonical = canonical_raw_counts(dataroot)

    for meta in manifest:
        path = Path(meta["blob_uri"])
        print(f"\n=== {path.name} ({meta['size_bytes']/1e6:.1f}MB) ===")
        with path.open("rb") as fp:
            reader = make_reader(fp)

            summary = reader.get_summary()
            if summary is None:
                bad("summary/인덱스 없음 — 랜덤 액세스 불가")
                continue
            ok(f"summary 존재 — 청크 인덱스 {len(summary.chunk_indexes)}개")

            schemas = {s.name: s.encoding for s in summary.schemas.values()}
            if "fleetsentinel.VehicleSignal" in schemas:
                ok(f"스키마 내장 확인: {sorted(schemas)} (encoding={set(schemas.values())})")
            else:
                bad(f"기대 스키마 없음: {sorted(schemas)}")

            topics = sorted(c.topic for c in summary.channels.values())
            expected = set(meta["sensor_channels"])
            if set(topics) == expected:
                ok(f"채널 {len(topics)}개 매니페스트와 일치")
            else:
                bad(f"채널 불일치 — 파일:{sorted(set(topics))} 매니페스트:{sorted(expected)}")

            counts = Counter()
            t_min, t_max = None, None
            for _, channel, message in reader.iter_messages():
                counts[channel.topic] += 1
                t_min = message.log_time if t_min is None else min(t_min, message.log_time)
                t_max = message.log_time if t_max is None else max(t_max, message.log_time)

            n_sig = counts["/vehicle/signal"]
            if n_sig == meta["n_signals"]:
                ok(f"신호 메시지 {n_sig}건 일치")
            else:
                bad(f"신호 수 불일치 file={n_sig} manifest={meta['n_signals']}")

            n_raw = sum(v for k, v in counts.items() if k.startswith(("/camera", "/lidar", "/radar")))
            if n_raw == meta["n_raw"]:
                ok(f"원시 센서 메시지 {n_raw}건 일치")
            else:
                bad(f"원시 수 불일치 file={n_raw} manifest={meta['n_raw']}")

            dur = (t_max - t_min) / 1e9
            rate = n_sig / dur if dur else 0
            ok(f"지속 {dur:.1f}s · 신호 {rate:.1f}Hz · 총 {sum(counts.values())}건")

            # 4) 구간 랜덤 액세스 — 중간 2초만 읽는다
            mid = t_min + (t_max - t_min) // 2
            window = [
                m for _, _, m in reader.iter_messages(start_time=mid, end_time=mid + 2_000_000_000)
            ]
            if window and all(mid <= m.log_time <= mid + 2_000_000_000 for m in window):
                ok(f"구간 랜덤 액세스 동작 — 중앙 2초 구간 {len(window)}건")
            else:
                bad("구간 랜덤 액세스 실패")

            # 5) 원시 페이로드가 진짜 바이트인가
            cam_topic = next((t for t in topics if t.startswith("/camera/CAM_FRONT")), None)
            if cam_topic:
                first = next(
                    (m for _, c, m in reader.iter_messages(topics=[cam_topic])), None
                )
                if first and first.data[:3] == b"\xff\xd8\xff":
                    ok(f"{cam_topic} 페이로드 JPEG 매직 확인 ({len(first.data):,}B)")
                else:
                    bad(f"{cam_topic} JPEG 매직 불일치")

            # 6) 무손실 계약 — 정본 sample_data 전량이 담겼는가
            ref = canonical.get(meta["scene_name"])
            if ref:
                if n_raw == ref["total"]:
                    ok(
                        f"무손실 계약: 원시 {n_raw}건 = 정본 {ref['total']}건 "
                        f"(키프레임 {ref['keyframe']} + 스윕 {ref['sweep']})"
                    )
                else:
                    bad(
                        f"무손실 계약 위반: MCAP {n_raw}건 vs 정본 {ref['total']}건 "
                        f"({100*n_raw/ref['total']:.1f}%) — 스윕 누락 회귀 의심"
                    )

            # 신호 1건 디코드 — 좌표 파생 확인
            sig = next((m for _, c, m in reader.iter_messages(topics=["/vehicle/signal"])), None)
            if sig:
                rec = json.loads(sig.data)
                has_geo = rec.get("lat") is not None and rec.get("lon") is not None
                has_can = rec.get("steering_rad") is not None
                ok(
                    f"신호 디코드 OK — lat/lon={'있음' if has_geo else '없음'} "
                    f"CAN={'있음' if has_can else '없음'} "
                    f"({rec['lat']:.5f}, {rec['lon']:.5f})"
                )

    print()
    if FAIL == 0:
        print("\033[32m== MCAP 검증 OK ==\033[0m")
    else:
        print("\033[31m== MCAP 검증 실패 ==\033[0m")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
