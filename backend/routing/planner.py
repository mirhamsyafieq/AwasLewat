"""Orkestrasi satu permintaan rute.

Alur: halte kandidat → perkiraan akses → graf request dengan node virtual →
Dijkstra per kategori → itinerary → pesan pengalihan → dedupe.
"""

from collections.abc import Callable
from dataclasses import dataclass

from backend.routing.access import AccessEstimate, AccessProvider
from backend.routing.dedupe import merge_duplicates
from backend.routing.dijkstra import find_path
from backend.routing.geo import nearest_stops
from backend.routing.graph import TransitGraph
from backend.routing.itinerary import build_itinerary
from backend.routing.models import Edge, Itinerary, Stop
from backend.routing.weights import (
    StepFunction,
    TripContext,
    cheapest_step,
    fastest_step,
)

ORIGIN_ID = "__origin__"
DESTINATION_ID = "__destination__"

REROUTE_TEMPLATE = "Dialihkan via {chosen} untuk menghindari macet di sekitar {nearest}"
REROUTE_SEPARATOR = "; "

# Kategori yang dicari: (badge, pembuat step function). F4.2 menambah dua lagi.
CATEGORIES: tuple[tuple[str, Callable[[TripContext], StepFunction]], ...] = (
    ("fastest", fastest_step),
    ("cheapest", cheapest_step),
)


@dataclass(frozen=True)
class Point:
    """Koordinat sembarang (titik awal atau tujuan)."""

    lat: float
    lon: float


@dataclass(frozen=True)
class Candidate:
    """Halte kandidat di dekat titik awal/tujuan beserta perkiraan aksesnya."""

    stop: Stop
    access: AccessEstimate


@dataclass
class RequestGraph:
    """Graf dasar + edge virtual untuk satu request.

    Graf dasar tidak diubah sama sekali (aman dipakai bersamaan oleh banyak
    request); edge dari `__origin__` dan menuju `__destination__` disimpan
    terpisah di `extra_edges_from`.
    """

    base: TransitGraph
    extra_edges_from: dict[str, list[Edge]]

    def has_stop(self, stop_id: str) -> bool:
        """True untuk halte asli maupun node virtual."""
        return stop_id in (ORIGIN_ID, DESTINATION_ID) or self.base.has_stop(stop_id)

    def outgoing(self, stop_id: str) -> list[Edge]:
        """Edge dari graf dasar ditambah edge virtual dari halte ini."""
        return self.base.outgoing(stop_id) + self.extra_edges_from.get(stop_id, [])


def find_candidates(
    graph: TransitGraph, point: Point, access: AccessProvider
) -> list[Candidate]:
    """Halte terdekat (maks. 3 dalam 2 km) dari `point`, terurut dari yang terdekat."""
    nearby = nearest_stops(graph.stops.values(), point.lat, point.lon)
    return [
        Candidate(stop, access.estimate(point.lat, point.lon, stop))
        for stop, _ in nearby
    ]


def _access_edge(from_id: str, to_id: str, estimate: AccessEstimate) -> Edge:
    """Edge virtual jalan kaki/berkendara antara node virtual dan halte."""
    return Edge(
        from_stop=from_id,
        to_stop=to_id,
        mode=estimate.mode,
        route_id=None,
        distance_km=estimate.distance_km,
        travel_min=estimate.minutes,
    )


def build_request_graph(
    graph: TransitGraph,
    origin_candidates: list[Candidate],
    destination_candidates: list[Candidate],
) -> RequestGraph:
    """Hubungkan `__origin__` ke semua kandidat awal dan kandidat tujuan ke `__destination__`.

    Dengan node virtual ini, satu kali Dijkstra langsung memilih pasangan halte
    naik/turun terbaik, termasuk memperhitungkan biaya aksesnya.
    """
    extra: dict[str, list[Edge]] = {ORIGIN_ID: []}
    for candidate in origin_candidates:
        extra[ORIGIN_ID].append(
            _access_edge(ORIGIN_ID, candidate.stop.id, candidate.access)
        )
    for candidate in destination_candidates:
        extra.setdefault(candidate.stop.id, []).append(
            _access_edge(candidate.stop.id, DESTINATION_ID, candidate.access)
        )
    return RequestGraph(base=graph, extra_edges_from=extra)


def reroute_note(candidates: list[Candidate], chosen_stop_id: str) -> str | None:
    """Pesan pengalihan untuk satu sisi (awal atau tujuan), atau None.

    Pesan hanya muncul bila (a) akses ke halte terdekat macet parah **dan**
    (b) halte yang dipilih Dijkstra bukan halte terdekat itu.
    """
    nearest = candidates[0]
    if not nearest.access.severe_jam or nearest.stop.id == chosen_stop_id:
        return None
    chosen = next(c.stop for c in candidates if c.stop.id == chosen_stop_id)
    return REROUTE_TEMPLATE.format(chosen=chosen.name, nearest=nearest.stop.name)


def build_reroute_message(
    edges: list[Edge],
    origin_candidates: list[Candidate],
    destination_candidates: list[Candidate],
) -> str | None:
    """Gabungkan pesan pengalihan sisi awal dan sisi tujuan (bila ada)."""
    boarding_stop = edges[0].to_stop  # edge pertama: __origin__ → halte kandidat
    alighting_stop = edges[
        -1
    ].from_stop  # edge terakhir: halte kandidat → __destination__

    notes = [
        reroute_note(origin_candidates, boarding_stop),
        reroute_note(destination_candidates, alighting_stop),
    ]
    present = [note for note in notes if note is not None]
    return REROUTE_SEPARATOR.join(present) if present else None


def plan_trip(
    graph: TransitGraph,
    origin: Point,
    destination: Point,
    trip: TripContext,
    access: AccessProvider,
) -> list[Itinerary]:
    """Cari rute dari `origin` ke `destination` untuk semua kategori.

    Mengembalikan daftar itinerary tanpa duplikat; kosong bila tidak ada halte
    dalam radius atau tujuan tidak terjangkau.
    """
    origin_candidates = find_candidates(graph, origin, access)
    destination_candidates = find_candidates(graph, destination, access)
    if not origin_candidates or not destination_candidates:
        return []

    request_graph = build_request_graph(
        graph, origin_candidates, destination_candidates
    )

    results = []
    for badge, make_step in CATEGORIES:
        found = find_path(request_graph, ORIGIN_ID, DESTINATION_ID, make_step(trip))
        if found is None:
            continue
        itinerary = build_itinerary(found.edges, ORIGIN_ID, trip)
        itinerary.badges.append(badge)
        itinerary.reroute_message = build_reroute_message(
            found.edges, origin_candidates, destination_candidates
        )
        results.append(itinerary)

    return merge_duplicates(results)
