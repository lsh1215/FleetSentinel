#!/usr/bin/env python3
"""데이터 실측 — `docs/data-design.md` 수치의 단일 근거.

문서에 적히는 모든 숫자가 여기서 나온다. 손으로 옮긴 값이 문서에 남지 않도록,
이 스크립트가 문서에 붙일 형태 그대로 출력한다.

측정 대상:
  §2  원천 규모 — 장면 수·길이·차량·지역
  §3.1 ③ 원시 센서 — 채널별 형식·Hz·크기·대역폭, 키프레임/스윕 구성
  §3.2 ① 신호 — 채널별 Hz·크기·필드(채널 네이티브 기준)
  §3.3 ② 인지 산출 — 키프레임 주기·객체 수·카테고리·품질 분포
  §7   품질 — LiDAR 미관측 비율, 시나리오 태그 희소성

사용:
    PYTHONPATH=. .venv/bin/python scripts/measure_dataset.py --dataroot ../data/nuscenes
    ... --json out.json      # 기계 판독용으로도 저장
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nuscenes.nuscenes import NuScenes  # noqa: E402

from fleetsentinel_ingest.nuscenes_source import extract_native_signals  # noqa: E402

#: 파일 확장자 → 사람이 읽는 형식 이름. 원시 센서 표의 "형식" 열이 여기서 나온다.
_FORMAT = {
    ".jpg": "JPEG 1600×900",
    ".bin": "`.pcd.bin` — float32 ×5 (x, y, z, intensity, ring)",
    ".pcd": "`.pcd` (텍스트 헤더 + 바이너리)",
}


def _fmt_bytes(n: float) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n:.0f} B"


def measure_source(nusc: NuScenes) -> Dict[str, Any]:
    """§2 — 원천이 무엇이고 얼마나 되는가."""
    scenes = []
    for sc in nusc.scene:
        first = nusc.get("sample", sc["first_sample_token"])
        last = nusc.get("sample", sc["last_sample_token"])
        log = nusc.get("log", sc["log_token"])
        scenes.append({
            "name": sc["name"],
            "duration_s": (last["timestamp"] - first["timestamp"]) / 1e6,
            "n_samples": sc["nbr_samples"],
            "location": log["location"],
            "vehicle": log["vehicle"],
            "date": log["date_captured"],
        })

    durations = [s["duration_s"] for s in scenes]
    return {
        "n_scenes": len(scenes),
        "total_duration_s": sum(durations),
        "duration_min_s": min(durations),
        "duration_max_s": max(durations),
        "duration_mean_s": statistics.mean(durations),
        "vehicles": sorted({s["vehicle"] for s in scenes}),
        "locations": sorted({s["location"] for s in scenes}),
        "dates": sorted({s["date"] for s in scenes}),
        "scenes": scenes,
    }


def measure_raw(nusc: NuScenes, dataroot: Path) -> Dict[str, Any]:
    """§3.1 — 원시 센서 12채널. 실제 파일 크기를 stat 한다."""
    per_channel: Dict[str, Dict[str, Any]] = {}
    key_n = key_bytes = sweep_n = sweep_bytes = 0
    missing = 0

    # 장면 전체 시간 합. 채널 Hz는 "건수 / 전체 녹화시간"으로 낸다.
    total_s = sum(
        (nusc.get("sample", sc["last_sample_token"])["timestamp"]
         - nusc.get("sample", sc["first_sample_token"])["timestamp"]) / 1e6
        for sc in nusc.scene
    )

    for sd in nusc.sample_data:
        ch = sd["channel"]
        path = dataroot / sd["filename"]
        if not path.exists():
            missing += 1
            continue
        size = path.stat().st_size
        e = per_channel.setdefault(ch, {"n": 0, "bytes": 0, "ext": path.suffix})
        e["n"] += 1
        e["bytes"] += size
        if sd["is_key_frame"]:
            key_n += 1
            key_bytes += size
        else:
            sweep_n += 1
            sweep_bytes += size

    rows = []
    for ch, e in per_channel.items():
        rows.append({
            "channel": ch,
            "format": _FORMAT.get(e["ext"], e["ext"]),
            "hz": e["n"] / total_s,
            "n": e["n"],
            "mean_bytes": e["bytes"] / e["n"],
            "bandwidth_mbps": e["bytes"] / total_s / 1024 / 1024,
        })
    rows.sort(key=lambda r: -r["bandwidth_mbps"])

    total_n = key_n + sweep_n
    total_bytes = key_bytes + sweep_bytes
    return {
        "total_duration_s": total_s,
        "channels": rows,
        "total_hz": sum(r["hz"] for r in rows),
        "total_bandwidth_mbps": sum(r["bandwidth_mbps"] for r in rows),
        "sample_data_total": total_n,
        "keyframe_n": key_n,
        "keyframe_ratio": key_n / total_n if total_n else 0,
        "keyframe_byte_ratio": key_bytes / total_bytes if total_bytes else 0,
        "sweep_n": sweep_n,
        "missing_files": missing,
    }


def measure_signals(nusc: NuScenes, can, n_scenes: int | None) -> Dict[str, Any]:
    """§3.2 — 신호. **채널 네이티브**가 기준이다.

    결합형(`SignalRecord`)은 ego_pose 주기로 다운샘플된 파생형이라 원천 규모를
    대표하지 못한다. 두 값을 함께 내서 그 차이를 명시한다.
    """
    scenes = nusc.scene if n_scenes is None else nusc.scene[:n_scenes]
    per_channel: Dict[str, Dict[str, Any]] = {}
    duration = 0.0
    n_joined = 0

    from fleetsentinel_ingest.nuscenes_source import extract_scene

    for sc in scenes:
        sigs = extract_native_signals(nusc, sc, vehicle_id="AV-0001", can_api=can)
        if not sigs:
            continue
        duration += (sigs[-1].sensor_time - sigs[0].sensor_time) / 1e6
        for s in sigs:
            e = per_channel.setdefault(
                s.channel, {"n": 0, "bytes": 0, "keys": collections.Counter()})
            e["n"] += 1
            # values만의 JSON 바이트. 헤더는 계층 공통이라 채널 비교에서 제외한다.
            e["bytes"] += len(json.dumps(s.values, separators=(",", ":")).encode())
            for k in s.values:
                e["keys"][k] += 1

        ex = extract_scene(nusc, sc, vehicle_id="AV-0001", can_api=can, include_sweeps=False)
        n_joined += len(ex.signals)

    rows = []
    for ch, e in per_channel.items():
        rows.append({
            "channel": ch,
            "n": e["n"],
            "hz": e["n"] / duration,
            "mean_values_bytes": e["bytes"] / e["n"],
            "keys": sorted(e["keys"]),
        })
    rows.sort(key=lambda r: -r["hz"])

    total_n = sum(r["n"] for r in rows)
    total_bytes = sum(per_channel[r["channel"]]["bytes"] for r in rows)
    return {
        "n_scenes": len(scenes),
        "duration_s": duration,
        "channels": rows,
        "total_n": total_n,
        "total_hz": total_n / duration,
        "mean_values_bytes": total_bytes / total_n,
        "joined_n": n_joined,
        "joined_ratio": n_joined / total_n if total_n else 0,
    }


def measure_perception(nusc: NuScenes) -> Dict[str, Any]:
    """§3.3 · §7.1 — 인지 산출과 라벨 품질."""
    total_s = sum(
        (nusc.get("sample", sc["last_sample_token"])["timestamp"]
         - nusc.get("sample", sc["first_sample_token"])["timestamp"]) / 1e6
        for sc in nusc.scene
    )

    per_keyframe = []
    categories = collections.Counter()
    visibility = collections.Counter()
    attributes = collections.Counter()
    lidar_zero = 0
    radar_zero = 0
    n_ann = 0
    intervals = []

    for sc in nusc.scene:
        token = sc["first_sample_token"]
        prev_t = None
        while token:
            sample = nusc.get("sample", token)
            anns = sample["anns"]
            per_keyframe.append(len(anns))
            if prev_t is not None:
                intervals.append((sample["timestamp"] - prev_t) / 1e6)
            prev_t = sample["timestamp"]

            for at in anns:
                ann = nusc.get("sample_annotation", at)
                n_ann += 1
                categories[ann["category_name"]] += 1
                if ann["num_lidar_pts"] == 0:
                    lidar_zero += 1
                if ann["num_radar_pts"] == 0:
                    radar_zero += 1
                vis = nusc.get("visibility", ann["visibility_token"])
                visibility[vis["level"]] += 1
                for att in ann["attribute_tokens"]:
                    attributes[nusc.get("attribute", att)["name"]] += 1
            token = sample["next"]

    n_keyframes = len(per_keyframe)
    return {
        "n_keyframes": n_keyframes,
        "keyframe_hz": n_keyframes / total_s,
        "mean_interval_s": statistics.mean(intervals) if intervals else 0,
        "objects_per_keyframe_mean": statistics.mean(per_keyframe),
        "objects_per_keyframe_max": max(per_keyframe),
        "objects_per_keyframe_min": min(per_keyframe),
        "objects_per_s": n_ann / total_s,
        "n_annotations": n_ann,
        "n_categories": len(categories),
        "categories": categories.most_common(),
        "visibility": visibility.most_common(),
        "attributes": attributes.most_common(),
        "lidar_zero_n": lidar_zero,
        "lidar_zero_ratio": lidar_zero / n_ann if n_ann else 0,
        "radar_zero_ratio": radar_zero / n_ann if n_ann else 0,
    }


def measure_scenario_tags(nusc: NuScenes) -> Dict[str, Any]:
    """§7.2 — 시나리오 태그(장면 description)가 얼마나 성긴가."""
    tags = collections.Counter()
    for sc in nusc.scene:
        for token in sc["description"].lower().replace(";", ",").split(","):
            t = token.strip()
            if t:
                tags[t] += 1
    night = sum(1 for sc in nusc.scene if "night" in sc["description"].lower())
    rain = sum(1 for sc in nusc.scene if "rain" in sc["description"].lower())
    return {
        "n_scenes": len(nusc.scene),
        "n_distinct_tags": len(tags),
        "tags": tags.most_common(),
        "night_scenes": night,
        "rain_scenes": rain,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataroot", type=Path, required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--signal-scenes", type=int, default=None,
                    help="신호 측정에 쓸 장면 수 (기본: 전체)")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    nusc = NuScenes(version=args.version, dataroot=str(args.dataroot), verbose=False)
    try:
        from nuscenes.can_bus.can_bus_api import NuScenesCanBus
        can = NuScenesCanBus(dataroot=str(args.dataroot))
    except Exception:
        can = None
        print("⚠️  CAN 확장 없음 — 신호가 ego_pose로 축소된다", file=sys.stderr)

    out = {
        "version": args.version,
        "source": measure_source(nusc),
        "raw": measure_raw(nusc, args.dataroot),
        "signals": measure_signals(nusc, can, args.signal_scenes),
        "perception": measure_perception(nusc),
        "scenario_tags": measure_scenario_tags(nusc),
    }

    s, r, sg, p, t = (out["source"], out["raw"], out["signals"],
                      out["perception"], out["scenario_tags"])

    print(f"═══ §2 원천 ({args.version}) ═══")
    print(f"  장면 {s['n_scenes']}개 · 총 {s['total_duration_s']:.1f}초")
    print(f"  장면 길이: 최소 {s['duration_min_s']:.1f}s / 평균 {s['duration_mean_s']:.1f}s "
          f"/ 최대 {s['duration_max_s']:.1f}s")
    print(f"  수집 차량: {len(s['vehicles'])}대 {s['vehicles']}")
    print(f"  지역: {s['locations']}")
    print(f"  촬영일: {len(s['dates'])}일")

    print(f"\n═══ §3.1 ③ 원시 센서 ═══   (전체 {r['total_duration_s']:.1f}초 기준)")
    print(f"  {'채널':<20}{'Hz':>7}{'건수':>8}{'평균크기':>11}{'대역폭':>13}")
    for c in r["channels"]:
        print(f"  {c['channel']:<20}{c['hz']:>7.1f}{c['n']:>8,}"
              f"{_fmt_bytes(c['mean_bytes']):>11}{c['bandwidth_mbps']:>10.2f} MB/s")
    print(f"  {'합계':<20}{r['total_hz']:>7.1f}{r['sample_data_total']:>8,}"
          f"{'':>11}{r['total_bandwidth_mbps']:>10.2f} MB/s")
    print(f"  키프레임 {r['keyframe_n']:,}/{r['sample_data_total']:,} "
          f"= {r['keyframe_ratio']*100:.1f}% (바이트 {r['keyframe_byte_ratio']*100:.1f}%) "
          f"→ 스윕이 {(1-r['keyframe_ratio'])*100:.1f}%")
    if r["missing_files"]:
        print(f"  ⚠️ 파일 없음 {r['missing_files']:,}건 — 측정에서 제외")

    print(f"\n═══ §3.2 ① 신호 (채널 네이티브) ═══   "
          f"({sg['n_scenes']}장면 {sg['duration_s']:.1f}초)")
    print(f"  {'채널':<22}{'Hz':>9}{'건수':>9}{'values 평균':>13}  필드")
    for c in sg["channels"]:
        keys = ", ".join(f"`{k}`" for k in c["keys"])
        print(f"  {c['channel']:<22}{c['hz']:>9.1f}{c['n']:>9,}"
              f"{c['mean_values_bytes']:>11.0f} B  {keys[:70]}")
    print(f"  {'합계':<22}{sg['total_hz']:>9.1f}{sg['total_n']:>9,}"
          f"{sg['mean_values_bytes']:>11.0f} B")
    print(f"  결합형(SignalRecord) {sg['joined_n']:,}건 = 네이티브의 "
          f"{sg['joined_ratio']*100:.1f}%")

    print(f"\n═══ §3.3 ② 인지 산출 ═══")
    print(f"  키프레임 {p['n_keyframes']:,}개 · {p['keyframe_hz']:.2f} Hz "
          f"(평균 간격 {p['mean_interval_s']:.3f}초)")
    print(f"  키프레임당 객체: 평균 {p['objects_per_keyframe_mean']:.1f} / "
          f"최소 {p['objects_per_keyframe_min']} / 최대 {p['objects_per_keyframe_max']}")
    print(f"  객체 발생률 {p['objects_per_s']:.1f} 객체/초 · 총 {p['n_annotations']:,}건")
    print(f"  카테고리 {p['n_categories']}종")

    print(f"\n═══ §7 품질 ═══")
    print(f"  LiDAR 0포인트: {p['lidar_zero_n']:,}/{p['n_annotations']:,} "
          f"= {p['lidar_zero_ratio']*100:.1f}%")
    print(f"  레이더 0포인트: {p['radar_zero_ratio']*100:.1f}%")
    print(f"  visibility 분포:")
    for lvl, n in p["visibility"]:
        print(f"    {lvl:<10} {n:>6,} ({n/p['n_annotations']*100:>5.1f}%)")
    print(f"  상위 카테고리:")
    for cat, n in p["categories"][:8]:
        print(f"    {cat:<34} {n:>6,} ({n/p['n_annotations']*100:>5.1f}%)")
    print(f"  시나리오 태그: {t['n_distinct_tags']}종 / {t['n_scenes']}장면 "
          f"· night {t['night_scenes']}개 · rain {t['rain_scenes']}개")

    if args.json:
        args.json.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"\nJSON → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
