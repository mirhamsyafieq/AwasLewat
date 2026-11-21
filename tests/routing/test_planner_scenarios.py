"""10 skenario rute dari titik sembarang + skenario macet.

Memakai fixture `jabodetabek_small.json` (koordinat perkiraan, bukan data asli)
dan akses fallback tanpa jaringan, jadi test tidak pernah memanggil OSRM/TomTom.
"""

import itertools
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.routing.access import (
    AccessEstimate,
    HaversineAccessProvider,
    apply_traffic,
)
from backend.routing.dedupe import BADGE_ORDER, itinerary_key
from backend.routing.fares import FareConfig
from backend.routing.graph import TransitGraph, build_graph, load_network
from backend.routing.models import Itinerary, Stop
from backend.routing.planner import DESTINATION_ID, ORIGIN_ID, Point, plan_trip
from backend.routing.weights import TripContext

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jabodetabek_small.json"
MAX_PLAN_SECONDS = 2.0
JAMMED_SPEED_KMH = 5.0


@pytest.fixture(scope="module")
def jabodetabek_graph() -> TransitGraph:
    """Graf dibangun sekali untuk semua skenario (seperti saat server start)."""
    stops, segments = load_network(FIXTURE_PATH)
    return build_graph(stops, segments)


@pytest.fixture
def trip(jabodetabek_graph: TransitGraph) -> TripContext:
    return TripContext(
        hour=10,
        fare_config=FareConfig(),
        krl_km_between=jabodetabek_graph.krl_km_between,
    )


@dataclass(frozen=True)
class Scenario:
    name: str
    origin: Point
    destination: Point
    required_modes: frozenset[str]


SCENARIOS = [
    Scenario("Depok → Monas", Point(-6.3920, 106.8230), Point(-6.1754, 106.8272), frozenset({"krl"})),
    Scenario("Bekasi → Blok M", Point(-6.2380, 107.0010), Point(-6.2440, 106.7990), frozenset({"krl", "brt"})),
    Scenario("Bogor → Sudirman", Point(-6.5980, 106.7990), Point(-6.2080, 106.8220), frozenset({"krl"})),
    Scenario("UI → Bundaran HI", Point(-6.3628, 106.8269), Point(-6.1950, 106.8231), frozenset({"krl"})),
    Scenario("Tebet → Kota Tua", Point(-6.2280, 106.8560), Point(-6.1352, 106.8133), frozenset({"krl"})),
    Scenario("Jatinegara → GBK", Point(-6.2150, 106.8710), Point(-6.2186, 106.8022), frozenset({"krl", "brt"})),
    Scenario("Pasar Minggu → Tanah Abang", Point(-6.2850, 106.8440), Point(-6.1860, 106.8120), frozenset({"krl"})),
    Scenario("Klender → Harmoni", Point(-6.2135, 106.9000), Point(-6.1655, 106.8205), frozenset({"krl"})),
    Scenario("Cikini → Blok M", Point(-6.1990, 106.8420), Point(-6.2440, 106.7990), frozenset({"krl", "brt"})),
    Scenario("Citayam → Jakarta Kota", Point(-6.4480, 106.8030), Point(-6.1380, 106.8150), frozenset({"krl"})),
]  # fmt: skip


def assert_valid_itinerary(itinerary: Itinerary) -> None:
    """Rute valid: mulai di titik awal, berakhir di tujuan, leg tersambung."""
    legs = itinerary.legs
    assert legs[0].from_stop == ORIGIN_ID
    assert legs[-1].to_stop == DESTINATION_ID
    for previous, current in itertools.pairwise(legs):
        assert previous.to_stop == current.from_stop

    vehicle_legs = [leg for leg in legs if leg.route_id is not None]
    assert vehicle_legs, "titik awal dan tujuan > 4 km, harus naik kendaraan"
    assert itinerary.transfers == len(vehicle_legs) - 1
    assert itinerary.total_min > 0
    assert itinerary.total_fare_idr >= 0
    assert itinerary.badges


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_scenario(
    scenario: Scenario, jabodetabek_graph: TransitGraph, trip: TripContext
) -> None:
    started = time.perf_counter()
    itineraries = plan_trip(
        jabodetabek_graph,
        scenario.origin,
        scenario.destination,
        trip,
        HaversineAccessProvider(),
    )
    elapsed = time.perf_counter() - started

    assert itineraries, "harus ada minimal satu rute"
    assert elapsed < MAX_PLAN_SECONDS

    keys = [itinerary_key(itinerary) for itinerary in itineraries]
    assert len(keys) == len(set(keys)), "tidak boleh ada kartu duplikat"

    all_badges = [badge for it in itineraries for badge in it.badges]
    # Tiap kategori menghasilkan tepat satu badge, tersebar di kartu yang ada.
    assert sorted(all_badges) == sorted(BADGE_ORDER)

    for itinerary in itineraries:
        assert_valid_itinerary(itinerary)
        modes = {leg.mode for leg in itinerary.legs}
        assert scenario.required_modes <= modes
        # Tanpa data macet, tidak boleh ada pesan pengalihan.
        assert itinerary.reroute_message is None


class FakeTrafficAccess:
    """Akses palsu: fallback haversine + kecepatan lalu lintas buatan per halte."""

    def __init__(self, speeds_kmh: dict[str, float]) -> None:
        self.fallback = HaversineAccessProvider()
        self.speeds_kmh = speeds_kmh

    def estimate(self, lat: float, lon: float, stop: Stop) -> AccessEstimate:
        base = self.fallback.estimate(lat, lon, stop)
        return apply_traffic(base, self.speeds_kmh.get(stop.id))


# Titik di antara Cakung (~1,2 km, terdekat) dan Kranji (~1,9 km); keduanya
# diakses dengan berkendara. Tujuan di Jatinegara (ke arah barat).
JAM_ORIGIN = Point(-6.2211, 106.9626)
JAM_DESTINATION = Point(-6.2150, 106.8710)


def _boarding_stops(itineraries: list[Itinerary]) -> set[str]:
    return {it.legs[0].to_stop for it in itineraries}


def test_no_reroute_without_jam(
    jabodetabek_graph: TransitGraph, trip: TripContext
) -> None:
    itineraries = plan_trip(
        jabodetabek_graph, JAM_ORIGIN, JAM_DESTINATION, trip, FakeTrafficAccess({})
    )
    assert _boarding_stops(itineraries) == {"CUK"}
    assert all(it.reroute_message is None for it in itineraries)


def test_reroute_when_nearest_stop_jammed(
    jabodetabek_graph: TransitGraph, trip: TripContext
) -> None:
    access = FakeTrafficAccess({"CUK": JAMMED_SPEED_KMH})
    itineraries = plan_trip(
        jabodetabek_graph, JAM_ORIGIN, JAM_DESTINATION, trip, access
    )

    assert _boarding_stops(itineraries) == {"KRI"}
    for itinerary in itineraries:
        assert_valid_itinerary(itinerary)
        assert itinerary.reroute_message == (
            "Dialihkan via Kranji untuk menghindari macet di sekitar Cakung"
        )


def test_no_candidates_returns_empty(
    jabodetabek_graph: TransitGraph, trip: TripContext
) -> None:
    middle_of_sea = Point(-5.90, 106.80)
    itineraries = plan_trip(
        jabodetabek_graph,
        middle_of_sea,
        JAM_DESTINATION,
        trip,
        HaversineAccessProvider(),
    )
    assert itineraries == []


def test_base_graph_not_modified(
    jabodetabek_graph: TransitGraph, trip: TripContext
) -> None:
    edge_count_before = sum(len(e) for e in jabodetabek_graph.edges_from.values())
    plan_trip(
        jabodetabek_graph,
        SCENARIOS[0].origin,
        SCENARIOS[0].destination,
        trip,
        HaversineAccessProvider(),
    )
    edge_count_after = sum(len(e) for e in jabodetabek_graph.edges_from.values())
    assert edge_count_after == edge_count_before
    assert not jabodetabek_graph.has_stop(ORIGIN_ID)
