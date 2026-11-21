"""Fixture pytest bersama untuk test mesin rute."""

from pathlib import Path

import pytest

from backend.routing.fares import FareConfig, load_fare_config
from backend.routing.graph import TransitGraph, build_graph, load_network
from backend.routing.weights import TripContext

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OFF_PEAK_HOUR = 10


@pytest.fixture
def fare_config() -> FareConfig:
    """Konfigurasi tarif dari fixture JSON."""
    return load_fare_config(FIXTURES_DIR / "fares.json")


@pytest.fixture
def mini_graph() -> TransitGraph:
    """Graf mini fiktif (lihat komentar di mini_graph.json)."""
    stops, segments = load_network(FIXTURES_DIR / "mini_graph.json")
    return build_graph(stops, segments)


@pytest.fixture
def off_peak_trip(fare_config: FareConfig, mini_graph: TransitGraph) -> TripContext:
    """Perjalanan pukul 10.00 di graf mini: tarif TJ normal, bus tidak di jam sibuk."""
    return TripContext(
        hour=OFF_PEAK_HOUR,
        fare_config=fare_config,
        krl_km_between=mini_graph.krl_km_between,
    )
