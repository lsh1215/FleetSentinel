"""geo 변환 계약 검증 — docs/data-design-v3.md §8 (R-V3-1)."""

from __future__ import annotations

import math

import pytest

from fleetsentinel_ingest.geo import (
    MAP_ORIGINS,
    UnknownLocationError,
    enu_to_wgs84,
    web_mercator_scale,
    wgs84_to_enu,
)

LOCATIONS = sorted(MAP_ORIGINS)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6378137.0
    p = math.radians
    h = (
        math.sin(p(lat2 - lat1) / 2) ** 2
        + math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(p(lon2 - lon1) / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


@pytest.mark.parametrize("location", LOCATIONS)
def test_origin_maps_to_itself(location: str) -> None:
    """ENU 원점(0,0)은 그 지도의 남서쪽 모서리 좌표로 변환돼야 한다."""
    lat, lon = enu_to_wgs84(0.0, 0.0, location)
    assert (lat, lon) == pytest.approx(MAP_ORIGINS[location], abs=1e-9)


@pytest.mark.parametrize("location", LOCATIONS)
@pytest.mark.parametrize("x,y", [(0.0, 0.0), (500.0, 1200.0), (1935.3, 870.2), (-30.0, 42.5)])
def test_round_trip_is_lossless(location: str, x: float, y: float) -> None:
    """ENU→WGS84→ENU 왕복은 밀리미터 이하로 원본을 복원해야 한다."""
    back_x, back_y = wgs84_to_enu(*enu_to_wgs84(x, y, location), location)
    assert math.hypot(back_x - x, back_y - y) < 1e-3


@pytest.mark.parametrize("location", LOCATIONS)
def test_east_increases_longitude_north_increases_latitude(location: str) -> None:
    """축 방향 계약: x=동쪽(경도 증가), y=북쪽(위도 증가)."""
    ref_lat, ref_lon = MAP_ORIGINS[location]
    east_lat, east_lon = enu_to_wgs84(1000.0, 0.0, location)
    north_lat, north_lon = enu_to_wgs84(0.0, 1000.0, location)

    assert east_lon > ref_lon
    assert north_lat > ref_lat
    # 각 축 이동은 직교 성분을 거의 바꾸지 않는다.
    assert east_lat == pytest.approx(ref_lat, abs=1e-3)
    assert north_lon == pytest.approx(ref_lon, abs=1e-3)


@pytest.mark.parametrize("location", LOCATIONS)
def test_distance_is_preserved(location: str) -> None:
    """변환 후 두 점 사이 실거리가 ENU 거리와 0.1% 이내로 일치해야 한다."""
    a, b = (300.0, 700.0), (1200.0, 1600.0)
    enu_dist = math.hypot(b[0] - a[0], b[1] - a[1])
    geo_dist = haversine_m(*enu_to_wgs84(*a, location), *enu_to_wgs84(*b, location))
    assert geo_dist == pytest.approx(enu_dist, rel=1e-3)


def test_boston_web_mercator_scale_explains_the_1_35_report() -> None:
    """R-V3-1: 포럼이 보고한 보스턴 1.35x는 Web Mercator 축척계수였다.

    이 테스트는 그 정체를 고정한다 — 변환 함수가 이 상수를 쓰지 않는다는 사실이
    회귀로 깨지지 않도록 근거를 코드에 남긴다.
    """
    assert web_mercator_scale("boston-seaport") == pytest.approx(1.35, abs=0.01)
    for singapore in [loc for loc in LOCATIONS if loc.startswith("singapore")]:
        assert web_mercator_scale(singapore) == pytest.approx(1.0, abs=0.001)


def test_unknown_location_is_rejected() -> None:
    with pytest.raises(UnknownLocationError, match="seoul"):
        enu_to_wgs84(0.0, 0.0, "seoul")
