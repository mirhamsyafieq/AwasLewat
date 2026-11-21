"""Test haversine, pencarian halte terdekat, dan pencarian pasangan berbasis grid."""

import itertools
import random

import pytest

from backend.routing.geo import (
    find_close_pairs,
    haversine_km,
    nearest_stops,
    stop_distance_km,
)
from backend.routing.models import Stop

# Keliling bumi / 360 dengan R = 6371 km.
KM_PER_DEGREE_ON_SPHERE = 111.195


def test_haversine_zero_for_same_point() -> None:
    assert haversine_km(-6.2, 106.8, -6.2, 106.8) == 0.0


def test_haversine_one_degree_latitude() -> None:
    assert haversine_km(0.0, 106.8, 1.0, 106.8) == pytest.approx(
        KM_PER_DEGREE_ON_SPHERE, abs=0.01
    )


def test_haversine_is_symmetric() -> None:
    there = haversine_km(-6.60, 106.80, -6.17, 106.83)
    back = haversine_km(-6.17, 106.83, -6.60, 106.80)
    assert there == pytest.approx(back)


def _stop(stop_id: str, lat: float, lon: float) -> Stop:
    return Stop(id=stop_id, name=stop_id, lat=lat, lon=lon)


def test_nearest_stops_sorted_and_limited() -> None:
    stops = [
        _stop("far", -6.200, 106.830),  # ~3,3 km: di luar radius 2 km
        _stop("mid", -6.200, 106.810),  # ~1,1 km
        _stop("near", -6.200, 106.801),  # ~0,1 km
        _stop("mid2", -6.200, 106.815),  # ~1,7 km
        _stop("mid3", -6.200, 106.812),  # ~1,3 km
    ]
    result = nearest_stops(stops, lat=-6.200, lon=106.800, count=3, radius_km=2.0)

    assert [stop.id for stop, _ in result] == ["near", "mid", "mid3"]
    distances = [distance for _, distance in result]
    assert distances == sorted(distances)


def test_nearest_stops_empty_when_nothing_in_radius() -> None:
    stops = [_stop("far", -6.5, 106.8)]
    assert nearest_stops(stops, lat=-6.2, lon=106.8) == []


def _brute_force_pairs(stops: list[Stop], max_km: float) -> set[frozenset[str]]:
    """Cara lambat O(n²) sebagai pembanding hasil grid."""
    return {
        frozenset((a.id, b.id))
        for a, b in itertools.combinations(stops, 2)
        if stop_distance_km(a, b) <= max_km
    }


@pytest.mark.parametrize("seed", range(5))
def test_find_close_pairs_matches_brute_force(seed: int) -> None:
    rng = random.Random(seed)
    stops = [
        _stop(f"S{i}", rng.uniform(-6.30, -6.10), rng.uniform(106.70, 106.90))
        for i in range(300)
    ]
    grid_pairs = {frozenset((a.id, b.id)) for a, b, _ in find_close_pairs(stops, 0.4)}
    assert grid_pairs == _brute_force_pairs(stops, 0.4)


def test_find_close_pairs_returns_each_pair_once() -> None:
    stops = [
        _stop("A", -6.2, 106.8),
        _stop("B", -6.2, 106.801),
        _stop("C", -6.2, 106.802),
    ]
    pairs = find_close_pairs(stops, 0.4)
    ids = [(a.id, b.id) for a, b, _ in pairs]
    assert len(ids) == len(set(ids)) == 3


def test_find_close_pairs_empty_input() -> None:
    assert find_close_pairs([], 0.4) == []
