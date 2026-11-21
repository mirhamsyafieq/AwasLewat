"""Test perkiraan akses ke halte: pilihan moda, fallback, dan efek macet."""

import pytest

from backend.routing.access import (
    DRIVE_FALLBACK_SPEED_KMH,
    MIN_TRAFFIC_SPEED_KMH,
    ROAD_DETOUR_FACTOR,
    AccessEstimate,
    HaversineAccessProvider,
    apply_traffic,
    choose_access_mode,
    minutes_at_speed,
)
from backend.routing.geo import haversine_km
from backend.routing.graph import WALK_SPEED_KMH
from backend.routing.models import DRIVE, WALK, Stop

STOP = Stop("S", "Halte S", -6.2000, 106.8000)
DRIVE_ESTIMATE = AccessEstimate("S", DRIVE, distance_km=2.0, minutes=6.0)


def test_choose_access_mode_by_distance() -> None:
    assert choose_access_mode(0.5) == WALK
    assert choose_access_mode(1.0) == WALK
    assert choose_access_mode(1.01) == DRIVE


def test_fallback_walk_access() -> None:
    lat, lon = -6.2000, 106.8050  # ~0,55 km dari STOP
    estimate = HaversineAccessProvider().estimate(lat, lon, STOP)

    road_km = haversine_km(lat, lon, STOP.lat, STOP.lon) * ROAD_DETOUR_FACTOR
    assert estimate.mode == WALK
    assert estimate.distance_km == pytest.approx(road_km)
    assert estimate.minutes == pytest.approx(minutes_at_speed(road_km, WALK_SPEED_KMH))
    assert not estimate.traffic_unknown


def test_fallback_drive_access_marks_traffic_unknown() -> None:
    lat, lon = -6.2000, 106.8150  # ~1,7 km dari STOP
    estimate = HaversineAccessProvider().estimate(lat, lon, STOP)

    assert estimate.mode == DRIVE
    assert estimate.minutes == pytest.approx(
        minutes_at_speed(estimate.distance_km, DRIVE_FALLBACK_SPEED_KMH)
    )
    assert estimate.traffic_unknown


def test_apply_traffic_ignores_walking() -> None:
    walk = AccessEstimate("S", WALK, 0.5, 6.7)
    assert apply_traffic(walk, current_speed_kmh=3.0) == walk


def test_apply_traffic_unknown_speed() -> None:
    result = apply_traffic(DRIVE_ESTIMATE, current_speed_kmh=None)
    assert result.minutes == DRIVE_ESTIMATE.minutes
    assert result.traffic_unknown
    assert not result.severe_jam


def test_apply_traffic_severe_jam() -> None:
    result = apply_traffic(DRIVE_ESTIMATE, current_speed_kmh=5.0)
    assert result.minutes == pytest.approx(24.0)  # 2 km / 5 km/jam
    assert result.severe_jam
    assert not result.traffic_unknown


def test_apply_traffic_smooth_road() -> None:
    result = apply_traffic(DRIVE_ESTIMATE, current_speed_kmh=30.0)
    assert result.minutes == pytest.approx(4.0)
    assert not result.severe_jam


def test_apply_traffic_zero_speed_does_not_crash() -> None:
    result = apply_traffic(DRIVE_ESTIMATE, current_speed_kmh=0.0)
    assert result.minutes == pytest.approx(minutes_at_speed(2.0, MIN_TRAFFIC_SPEED_KMH))
    assert result.severe_jam
