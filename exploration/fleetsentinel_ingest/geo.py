"""nuScenes ENU 로컬 좌표 ↔ WGS84 위경도 변환.

nuScenes `ego_pose.translation`은 위경도가 아니라 **지역 지도의 ENU(East-North-Up)
로컬 미터 좌표**이고 z는 항상 0이다(실측 확인). Kibana Maps의 `geo_point`는 WGS84를
요구하므로 변환이 필요하다 — docs/data-design.md §8.

원점은 각 지도의 **남서쪽 모서리**이며, 값은 nuscenes-devkit
`nuscenes/map_expansion/map_api.py` 45–49행에 문서화된 공식 좌표다.

## "보스턴 1.35x 스케일링"에 대하여

커뮤니티에서 보스턴 좌표에 1.35배 스케일링이 필요하다고 보고돼 왔다(설계 문서 R-V3-1).
검증 결과 이는 **Web Mercator(EPSG:3857) 축척계수 1/cos(lat)** 의 다른 이름이었다.

    boston-seaport (42.34°N)  → 1/cos(lat) = 1.3528  ≈ 보고값 1.35
    singapore 3곳  (~1.29°N)  → 1/cos(lat) = 1.0003  ≈ 보정 불필요

즉 Web Mercator로 작업할 때만 필요한 보정이고, 아래처럼 **로컬 접평면 또는 대권
방식으로 직접 변환하면 어떤 보정 상수도 필요 없다**.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

# WGS84 장반경(m). nuscenes2mcap 참조 구현과 동일 상수를 쓴다.
EARTH_RADIUS_M = 6378137.0

# 각 지도의 남서쪽 모서리 원점 [위도, 경도].
# 출처: nuscenes-devkit map_expansion/map_api.py L45-49 (공식 문서화 값).
MAP_ORIGINS: Dict[str, Tuple[float, float]] = {
    "boston-seaport": (42.336849169438615, -71.05785369873047),
    "singapore-onenorth": (1.2882100868743724, 103.78475189208984),
    "singapore-hollandvillage": (1.2993652317780957, 103.78217697143555),
    "singapore-queenstown": (1.2782562240223188, 103.76741409301758),
}


class UnknownLocationError(KeyError):
    """MAP_ORIGINS에 없는 지역 이름."""


def _origin(location: str) -> Tuple[float, float]:
    try:
        return MAP_ORIGINS[location]
    except KeyError as exc:
        raise UnknownLocationError(
            f"알 수 없는 지역 '{location}'. 지원: {sorted(MAP_ORIGINS)}"
        ) from exc


def enu_to_wgs84(x: float, y: float, location: str) -> Tuple[float, float]:
    """ENU 로컬 미터 좌표를 WGS84 위경도로 변환한다(대권 방식).

    원점에서의 방위각과 거리로 목적지 좌표를 구하는 표준식을 쓴다. 이동에 따른
    경도 수렴 변화를 반영하므로 접평면 근사보다 원점에서 멀 때 정확하다.
    nuscenes2mcap `derive_latlon()`과 동일한 방법이다.

    :param x: 동쪽 방향 거리(m) — `ego_pose.translation[0]`
    :param y: 북쪽 방향 거리(m) — `ego_pose.translation[1]`
    :param location: `log.location` (예: "boston-seaport")
    :returns: (위도, 경도) degrees
    """
    ref_lat, ref_lon = _origin(location)
    lat_rad, lon_rad = math.radians(ref_lat), math.radians(ref_lon)

    bearing = math.atan2(x, y)
    angular_distance = math.hypot(x, y) / EARTH_RADIUS_M

    target_lat = math.asin(
        math.sin(lat_rad) * math.cos(angular_distance)
        + math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing)
    )
    target_lon = lon_rad + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat_rad),
        math.cos(angular_distance) - math.sin(lat_rad) * math.sin(target_lat),
    )
    return math.degrees(target_lat), math.degrees(target_lon)


def wgs84_to_enu(lat: float, lon: float, location: str) -> Tuple[float, float]:
    """WGS84 위경도를 ENU 로컬 미터 좌표로 되돌린다(`enu_to_wgs84`의 역변환)."""
    ref_lat, ref_lon = _origin(location)
    lat_rad, lon_rad = math.radians(lat), math.radians(lon)
    ref_lat_rad, ref_lon_rad = math.radians(ref_lat), math.radians(ref_lon)

    d_lon = lon_rad - ref_lon_rad
    angular_distance = math.acos(
        max(
            -1.0,
            min(
                1.0,
                math.sin(ref_lat_rad) * math.sin(lat_rad)
                + math.cos(ref_lat_rad) * math.cos(lat_rad) * math.cos(d_lon),
            ),
        )
    )
    bearing = math.atan2(
        math.sin(d_lon) * math.cos(lat_rad),
        math.cos(ref_lat_rad) * math.sin(lat_rad)
        - math.sin(ref_lat_rad) * math.cos(lat_rad) * math.cos(d_lon),
    )
    dist = angular_distance * EARTH_RADIUS_M
    return dist * math.sin(bearing), dist * math.cos(bearing)


def web_mercator_scale(location: str) -> float:
    """해당 지역에서 Web Mercator를 쓸 때 필요한 축척계수 1/cos(lat).

    R-V3-1의 "보스턴 1.35x" 보고를 재현·설명하기 위한 함수다. 위 변환 함수들은
    이 보정을 필요로 하지 않는다 — Web Mercator 경유 파이프라인과 대조할 때만 쓴다.
    """
    ref_lat, _ = _origin(location)
    return 1.0 / math.cos(math.radians(ref_lat))
