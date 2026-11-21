"""Test kategori paling sedikit transit dan paling lengang di graf kecil.

Graf: dari A ke B ada dua pilihan.
- KRL: A → C (KRL-1, 10 menit), ganti di C ke KRL-2, C → B (10 menit). 2 kali naik.
- Bus Metrotrans langsung A → B (20 menit di jalan umum). 1 kali naik.
Semua headway 10 menit (tunggu 5 menit tiap naik).
"""

from collections.abc import Callable

import pytest

from backend.routing.crowd import CrowdConfig
from backend.routing.dijkstra import find_path
from backend.routing.fares import FareConfig
from backend.routing.graph import TransitGraph, build_graph
from backend.routing.models import Edge, Stop
from backend.routing.weights import (
    BUS_OFF_PEAK_MULTIPLIER,
    BUS_PEAK_MULTIPLIER,
    LEAST_CROWDED_TRANSFER_PENALTY_MIN,
    TRANSFER_PENALTY,
    StepFunction,
    TripContext,
    fastest_step,
    fewest_transfers_step,
    least_crowded_step,
)

OFF_PEAK_HOUR = 11
PEAK_HOUR = 7


@pytest.fixture
def two_option_graph() -> TransitGraph:
    stops = [
        Stop("A", "A", -6.30, 106.80),
        Stop("C", "C", -6.25, 106.82),
        Stop("B", "B", -6.20, 106.84),
    ]
    segments = [
        Edge("A", "C", "krl", "KRL-1", 6.0, 10.0, 10.0),
        Edge("C", "B", "krl", "KRL-2", 6.0, 10.0, 10.0),
        Edge("A", "B", "metrotrans", "BUS-1", 12.0, 20.0, 10.0),
    ]
    return build_graph(stops, segments)


def _trip(graph: TransitGraph, hour: int, crowd: CrowdConfig) -> TripContext:
    return TripContext(hour, FareConfig(), graph.krl_km_between, crowd)


def _routes(
    graph: TransitGraph,
    trip: TripContext,
    make_step: Callable[[TripContext], StepFunction],
) -> list[str | None]:
    result = find_path(graph, "A", "B", make_step(trip))
    assert result is not None
    return [edge.route_id for edge in result.edges]


def test_fastest_takes_krl(two_option_graph: TransitGraph) -> None:
    trip = _trip(two_option_graph, OFF_PEAK_HOUR, CrowdConfig())
    # KRL: 5 + 10 + 5 + 10 = 30 menit; bus: 5 + 20 × 1,5 = 35 menit.
    assert _routes(two_option_graph, trip, fastest_step) == ["KRL-1", "KRL-2"]


def test_fewest_transfers_takes_direct_bus(two_option_graph: TransitGraph) -> None:
    trip = _trip(two_option_graph, OFF_PEAK_HOUR, CrowdConfig())
    assert _routes(two_option_graph, trip, fewest_transfers_step) == ["BUS-1"]

    result = find_path(two_option_graph, "A", "B", fewest_transfers_step(trip))
    assert result is not None
    bus_minutes = 5.0 + 20.0 * BUS_OFF_PEAK_MULTIPLIER
    assert result.cost == pytest.approx(TRANSFER_PENALTY + bus_minutes)


def test_least_crowded_normal_day_takes_krl(two_option_graph: TransitGraph) -> None:
    trip = _trip(two_option_graph, PEAK_HOUR, CrowdConfig())
    # KRL: 2 × (5 + 10 × 2,0 + 5) = 60; bus: 5 + 20 × 3,0 × 1,3 + 5 = 88.
    assert _routes(two_option_graph, trip, least_crowded_step) == ["KRL-1", "KRL-2"]


def test_least_crowded_avoids_packed_krl(two_option_graph: TransitGraph) -> None:
    packed = CrowdConfig(route_overrides={"KRL-1": (4.0, 1.0), "KRL-2": (4.0, 1.0)})
    trip = _trip(two_option_graph, PEAK_HOUR, packed)
    # KRL: 2 × (5 + 10 × 4,0 + 5) = 100; bus tetap 88 → bus menang.
    assert _routes(two_option_graph, trip, least_crowded_step) == ["BUS-1"]

    result = find_path(two_option_graph, "A", "B", least_crowded_step(trip))
    assert result is not None
    bus_cost = (
        5.0 + 20.0 * BUS_PEAK_MULTIPLIER * 1.3 + LEAST_CROWDED_TRANSFER_PENALTY_MIN
    )
    assert result.cost == pytest.approx(bus_cost)
