"""Test Dijkstra: dibandingkan dengan NetworkX dan dengan hitungan tangan.

NetworkX hanya dipakai di sini sebagai pembanding, bukan di kode utama.
"""

import random

import networkx as nx
import pytest

from backend.routing.dijkstra import find_path
from backend.routing.fares import FareConfig
from backend.routing.geo import stop_distance_km
from backend.routing.graph import TransitGraph, build_graph, walk_minutes
from backend.routing.itinerary import build_itinerary
from backend.routing.models import WALK, Edge, Stop
from backend.routing.weights import TripContext, cheapest_step, fastest_step


def _random_krl_graph(seed: int) -> TransitGraph:
    """Graf acak: semua edge KRL dengan headway 0 dan tiap edge rute sendiri.

    Dengan headway 0 dan pengali 1,0, biaya tercepat = jumlah travel_min biasa,
    sehingga hasilnya bisa dibandingkan langsung dengan Dijkstra NetworkX.
    """
    rng = random.Random(seed)
    stops = [
        Stop(
            id=f"S{i}",
            name=f"S{i}",
            lat=rng.uniform(-6.4, -6.1),
            lon=rng.uniform(106.7, 107.0),
        )
        for i in range(40)
    ]
    segments = []
    for index in range(120):
        a, b = rng.sample(stops, 2)
        segments.append(
            Edge(
                a.id,
                b.id,
                "krl",
                f"R{index}",
                1.0,
                rng.uniform(1.0, 30.0),
                headway_min=0.0,
            )
        )
    return build_graph(stops, segments)


def _to_networkx(graph: TransitGraph) -> nx.DiGraph:
    """Salin graf ke NetworkX; bila ada edge paralel, ambil yang paling cepat."""
    nx_graph = nx.DiGraph()
    nx_graph.add_nodes_from(graph.stops)
    for edges in graph.edges_from.values():
        for edge in edges:
            current = nx_graph.get_edge_data(edge.from_stop, edge.to_stop)
            if current is None or edge.travel_min < current["weight"]:
                nx_graph.add_edge(edge.from_stop, edge.to_stop, weight=edge.travel_min)
    return nx_graph


@pytest.mark.parametrize("seed", range(3))
def test_fastest_matches_networkx_on_random_graphs(
    seed: int, fare_config: FareConfig
) -> None:
    graph = _random_krl_graph(seed)
    nx_graph = _to_networkx(graph)
    step = fastest_step(
        TripContext(
            hour=10, fare_config=fare_config, krl_km_between=graph.krl_km_between
        )
    )

    for start in graph.stops:
        expected = nx.single_source_dijkstra_path_length(nx_graph, start)
        for goal in graph.stops:
            result = find_path(graph, start, goal, step)
            if goal in expected:
                assert result is not None
                assert result.cost == pytest.approx(expected[goal])
            else:
                assert result is None


def _route_ids(edges: list[Edge]) -> list[str | None]:
    """Urutan route_id tanpa duplikat berurutan (None = jalan kaki)."""
    sequence: list[str | None] = []
    for edge in edges:
        if not sequence or sequence[-1] != edge.route_id:
            sequence.append(edge.route_id)
    return sequence


def test_fastest_on_mini_graph(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    result = find_path(mini_graph, "K1", "T3", fastest_step(off_peak_trip))
    assert result is not None
    assert _route_ids(result.edges) == ["KRL-L1", None, "BRT-1"]

    walk_min = walk_minutes(
        stop_distance_km(mini_graph.stops["K4"], mini_graph.stops["T1"])
    )
    krl_min = 5.0 + 25.0 + 22.0 + 6.0  # tunggu headway/2 + 3 segmen
    brt_min = 3.0 + 6.0 + 8.0
    assert result.cost == pytest.approx(krl_min + walk_min + brt_min)


def test_cheapest_prefers_free_mikrotrans(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    result = find_path(mini_graph, "K1", "T3", cheapest_step(off_peak_trip))
    assert result is not None
    assert _route_ids(result.edges) == ["KRL-L1", None, "MK-1"]

    itinerary = build_itinerary(result.edges, "K1", off_peak_trip)
    assert itinerary.total_fare_idr == 5_000  # KRL 42 km + Mikrotrans Rp0
    assert itinerary.transfers == 1


def test_itinerary_groups_edges_into_legs(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    result = find_path(mini_graph, "K1", "T3", fastest_step(off_peak_trip))
    assert result is not None
    itinerary = build_itinerary(result.edges, "K1", off_peak_trip)

    assert [leg.mode for leg in itinerary.legs] == ["krl", WALK, "brt"]
    krl_leg = itinerary.legs[0]
    assert (krl_leg.from_stop, krl_leg.to_stop) == ("K1", "K4")
    assert krl_leg.distance_km == pytest.approx(42.0)
    assert itinerary.total_min == pytest.approx(result.cost)


def test_unreachable_goal_returns_none(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    # Semua segmen fixture satu arah menuju T3, jadi dari T3 tidak bisa ke K1.
    assert find_path(mini_graph, "T3", "K1", fastest_step(off_peak_trip)) is None


def test_start_equals_goal(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    result = find_path(mini_graph, "K1", "K1", fastest_step(off_peak_trip))
    assert result is not None
    assert result.cost == 0.0
    assert result.edges == []


def test_unknown_stop_raises(
    mini_graph: TransitGraph, off_peak_trip: TripContext
) -> None:
    with pytest.raises(ValueError):
        find_path(mini_graph, "K1", "TIDAK-ADA", fastest_step(off_peak_trip))


def test_walk_edges_built_both_ways(mini_graph: TransitGraph) -> None:
    walk_targets_from_k4 = [
        e.to_stop for e in mini_graph.outgoing("K4") if e.mode == WALK
    ]
    walk_targets_from_t1 = [
        e.to_stop for e in mini_graph.outgoing("T1") if e.mode == WALK
    ]
    assert walk_targets_from_k4 == ["T1"]
    assert walk_targets_from_t1 == ["K4"]


def test_build_graph_rejects_unknown_stop() -> None:
    stops = [Stop("A", "A", -6.2, 106.8)]
    bad_segment = Edge("A", "Z", "krl", "R1", 1.0, 1.0, 1.0)
    with pytest.raises(ValueError):
        build_graph(stops, [bad_segment])
