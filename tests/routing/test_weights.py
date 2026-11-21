"""Test fungsi biaya per langkah (tanpa Dijkstra)."""

import pytest

from backend.routing.fares import FareConfig
from backend.routing.models import DRIVE, WALK, Edge, FareZone, SearchState
from backend.routing.weights import (
    BUS_OFF_PEAK_MULTIPLIER,
    BUS_PEAK_MULTIPLIER,
    FARE_WEIGHT,
    TripContext,
    cheapest_step,
    fastest_step,
    pending_krl_fare,
    step_fare,
    traffic_multiplier,
    wait_minutes,
)

KRL_EDGE = Edge(
    "A", "B", "krl", "KRL-L1", distance_km=20.0, travel_min=25.0, headway_min=10.0
)
BRT_EDGE = Edge("A", "B", "brt", "BRT-1", 2.0, 6.0, 6.0)
METROTRANS_EDGE = Edge("A", "B", "metrotrans", "MT-1", 3.0, 15.0, 15.0)
WALK_EDGE = Edge("A", "B", WALK, None, 0.3, 4.0)
DRIVE_EDGE = Edge("A", "B", DRIVE, None, 2.0, 6.0)

# Penumpang tap-in di X; jarak KRL terpendek X → A = 40 km (tarif Rp5.000).
KRL_TABLE = {"X": {"X": 0.0, "A": 40.0}}
IN_KRL_FROM_X = FareZone("krl", tap_in_stop="X")

AT_A_ON_FOOT = SearchState("A", route_id=None, fare_zone=None)
AT_A_ON_KRL_L1 = SearchState("A", route_id="KRL-L1", fare_zone=IN_KRL_FROM_X)
AT_A_ON_KRL_L2 = SearchState("A", route_id="KRL-L2", fare_zone=IN_KRL_FROM_X)


@pytest.fixture
def trip() -> TripContext:
    return TripContext(hour=10, fare_config=FareConfig(), krl_km_between=KRL_TABLE)


def test_wait_only_when_boarding() -> None:
    assert wait_minutes(AT_A_ON_FOOT, KRL_EDGE) == 5.0  # naik pertama: headway / 2
    assert wait_minutes(AT_A_ON_KRL_L1, KRL_EDGE) == 0.0  # tetap di kereta yang sama
    assert wait_minutes(AT_A_ON_KRL_L2, KRL_EDGE) == 5.0  # ganti jalur = tunggu lagi
    assert wait_minutes(AT_A_ON_KRL_L1, WALK_EDGE) == 0.0  # jalan kaki tidak menunggu
    assert wait_minutes(AT_A_ON_FOOT, DRIVE_EDGE) == 0.0  # akses ojek tidak menunggu


@pytest.mark.parametrize("hour", [0, 7, 17])
def test_segregated_modes_ignore_traffic(hour: int) -> None:
    for mode in ("krl", "brt", WALK, DRIVE):
        assert traffic_multiplier(mode, hour) == 1.0


def test_bus_traffic_multiplier_by_hour() -> None:
    assert traffic_multiplier("metrotrans", 10) == BUS_OFF_PEAK_MULTIPLIER
    assert traffic_multiplier("mikrotrans", 17) == BUS_PEAK_MULTIPLIER


def test_fastest_step_cost(trip: TripContext) -> None:
    step = fastest_step(trip)
    cost, zone = step(AT_A_ON_FOOT, METROTRANS_EDGE)
    assert cost == 7.5 + 15.0 * BUS_OFF_PEAK_MULTIPLIER
    assert zone is None


def test_boarding_krl_is_tap_in(trip: TripContext) -> None:
    rupiah, zone = step_fare(AT_A_ON_FOOT, KRL_EDGE, trip)
    assert rupiah == 0
    assert zone == FareZone("krl", tap_in_stop="A")


def test_riding_krl_costs_nothing_until_tap_out(trip: TripContext) -> None:
    assert step_fare(AT_A_ON_KRL_L1, KRL_EDGE, trip) == (0, IN_KRL_FROM_X)
    # Ganti jalur KRL di stasiun yang sama: tetap satu perjalanan.
    assert step_fare(AT_A_ON_KRL_L2, KRL_EDGE, trip) == (0, IN_KRL_FROM_X)


def test_walking_out_of_krl_pays_by_distance(trip: TripContext) -> None:
    # Tap-out di A: X → A = 40 km → Rp3.000 + 2 × Rp1.000.
    assert step_fare(AT_A_ON_KRL_L1, WALK_EDGE, trip) == (5_000, None)


def test_krl_to_tj_pays_both(trip: TripContext) -> None:
    rupiah, zone = step_fare(AT_A_ON_KRL_L1, BRT_EDGE, trip)
    assert rupiah == 5_000 + 3_500
    assert zone == FareZone("tj")


def test_pending_krl_fare(trip: TripContext) -> None:
    assert pending_krl_fare(AT_A_ON_KRL_L1, trip) == 5_000
    assert pending_krl_fare(AT_A_ON_FOOT, trip) == 0


def test_walking_then_tj_pays_again(trip: TripContext) -> None:
    rupiah, zone = step_fare(AT_A_ON_FOOT, BRT_EDGE, trip)
    assert rupiah == 3_500
    assert zone == FareZone("tj")


def test_drive_access_is_free_and_outside_paid_area(trip: TripContext) -> None:
    assert step_fare(AT_A_ON_FOOT, DRIVE_EDGE, trip) == (0, None)


def test_cheapest_step_puts_rupiah_before_minutes(trip: TripContext) -> None:
    step = cheapest_step(trip)
    cost, _ = step(AT_A_ON_KRL_L1, WALK_EDGE)
    assert cost == 5_000 * FARE_WEIGHT + 4.0


def test_all_step_costs_non_negative(trip: TripContext) -> None:
    edges = [KRL_EDGE, BRT_EDGE, METROTRANS_EDGE, WALK_EDGE, DRIVE_EDGE]
    states = [AT_A_ON_FOOT, AT_A_ON_KRL_L1, AT_A_ON_KRL_L2]
    for make_step in (fastest_step, cheapest_step):
        step = make_step(trip)
        for state in states:
            for edge in edges:
                cost, _ = step(state, edge)
                assert cost >= 0
