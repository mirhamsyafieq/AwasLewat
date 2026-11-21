"""Test aturan tarif: rumus dasar dan tarif total pada rute di graf mini."""

from dataclasses import replace

import pytest

from backend.routing.dijkstra import find_path
from backend.routing.fares import FareConfig, krl_fare, tj_fare
from backend.routing.graph import TransitGraph, build_graph
from backend.routing.itinerary import build_itinerary
from backend.routing.models import Edge, Stop
from backend.routing.weights import TripContext, fastest_step


@pytest.mark.parametrize(
    ("distance_km", "expected_idr"),
    [
        (0.0, 3_000),
        (10.0, 3_000),
        (25.0, 3_000),
        (25.1, 4_000),
        (26.0, 4_000),
        (35.0, 4_000),
        (36.0, 5_000),
        (45.0, 5_000),
        (46.0, 6_000),
    ],
)
def test_krl_fare_boundaries(
    distance_km: float, expected_idr: int, fare_config: FareConfig
) -> None:
    assert krl_fare(distance_km, fare_config) == expected_idr


@pytest.mark.parametrize(
    ("hour", "expected_idr"),
    [(4, 3_500), (5, 2_000), (6, 2_000), (7, 3_500), (22, 3_500)],
)
def test_tj_fare_morning_window(
    hour: int, expected_idr: int, fare_config: FareConfig
) -> None:
    assert tj_fare(hour, fare_config) == expected_idr


def test_fixture_matches_default_config(fare_config: FareConfig) -> None:
    assert fare_config == FareConfig()


def _fare_of_fastest_route(
    graph: TransitGraph, start: str, goal: str, trip: TripContext
) -> int:
    result = find_path(graph, start, goal, fastest_step(trip))
    assert result is not None
    return build_itinerary(result.edges, start, trip).total_fare_idr


def test_krl_long_trip_uses_cumulative_distance(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    # K1 → K4 = 20 + 18 + 4 = 42 km dalam satu kali naik → Rp3.000 + 2 × Rp1.000.
    assert _fare_of_fastest_route(mini_graph, "K1", "K4", off_peak_trip) == 5_000


def test_krl_line_change_is_one_trip(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    # K5 → K3 (KRL-L2, 10 km) lalu ganti ke KRL-L1 → K4 (4 km): total 14 km, satu tap-in.
    result = find_path(mini_graph, "K5", "K4", fastest_step(off_peak_trip))
    assert result is not None
    itinerary = build_itinerary(result.edges, "K5", off_peak_trip)

    assert [leg.route_id for leg in itinerary.legs] == ["KRL-L2", "KRL-L1"]
    assert itinerary.transfers == 1
    assert itinerary.total_fare_idr == 3_000


def test_tj_transfer_same_stop_is_free(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    # T4 → T2 (BRT-2), ganti di T2 ke BRT-1 → T3: cukup bayar sekali.
    assert _fare_of_fastest_route(mini_graph, "T4", "T3", off_peak_trip) == 3_500


def test_tj_transfer_paid_when_option_disabled(
    mini_graph: TransitGraph, fare_config: FareConfig
) -> None:
    config = replace(fare_config, tj_free_transfer_same_stop=False)
    trip = TripContext(
        hour=10, fare_config=config, krl_km_between=mini_graph.krl_km_between
    )
    assert _fare_of_fastest_route(mini_graph, "T4", "T3", trip) == 7_000


def test_tj_morning_fare_applies_to_route(
    mini_graph: TransitGraph, fare_config: FareConfig
) -> None:
    trip = TripContext(
        hour=6, fare_config=fare_config, krl_km_between=mini_graph.krl_km_between
    )
    assert _fare_of_fastest_route(mini_graph, "T4", "T3", trip) == 2_000


def test_krl_distance_table(mini_graph: TransitGraph) -> None:
    table = mini_graph.krl_km_between
    assert table["K1"]["K1"] == 0.0
    assert table["K1"]["K4"] == pytest.approx(42.0)
    assert table["K5"]["K4"] == pytest.approx(14.0)  # lewat K3, ganti jalur
    assert "K1" not in table["K5"]  # fixture satu arah: K5 tidak bisa ke K1


def test_krl_fare_uses_shortest_distance_not_path_taken() -> None:
    # Dua jalur dari A ke C: langsung 30 km, atau lewat B 10 + 40 = 50 km.
    stops = [
        Stop("A", "A", -6.0, 106.0),
        Stop("B", "B", -6.1, 106.1),
        Stop("C", "C", -6.2, 106.2),
    ]
    segments = [
        Edge("A", "C", "krl", "L1", 30.0, 60.0, 10.0),
        Edge("A", "B", "krl", "L2", 10.0, 5.0, 10.0),
        Edge("B", "C", "krl", "L2", 40.0, 5.0, 10.0),
    ]
    graph = build_graph(stops, segments)
    trip = TripContext(10, FareConfig(), graph.krl_km_between)

    # Tercepat lewat B (50 km ditempuh), tapi tarif dari jarak terpendek A → C = 30 km.
    result = find_path(graph, "A", "C", fastest_step(trip))
    assert result is not None
    assert [edge.to_stop for edge in result.edges] == ["B", "C"]
    assert build_itinerary(result.edges, "A", trip).total_fare_idr == 4_000
