"""Membangun graf transit dari data stops dan route_segments."""

import heapq
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.routing.geo import find_close_pairs
from backend.routing.models import WALK, Edge, Stop

MAX_WALK_TRANSFER_KM = 0.4
WALK_SPEED_KMH = 4.5
MINUTES_PER_HOUR = 60

# krl_km_between[tap_in][tap_out] = jarak KRL terpendek (km).
KrlDistanceTable = dict[str, dict[str, float]]


@dataclass
class TransitGraph:
    """Graf berarah dalam bentuk adjacency list.

    `edges_from[stop_id]` = daftar semua edge yang keluar dari halte itu.
    `krl_km_between` = tabel jarak KRL terpendek antarstasiun, untuk tarif KRL.
    """

    stops: dict[str, Stop]
    edges_from: dict[str, list[Edge]]
    krl_km_between: KrlDistanceTable

    def has_stop(self, stop_id: str) -> bool:
        """True bila halte `stop_id` ada di graf."""
        return stop_id in self.stops

    def outgoing(self, stop_id: str) -> list[Edge]:
        """Semua edge yang keluar dari `stop_id` (kosong bila tidak ada)."""
        return self.edges_from.get(stop_id, [])


class SearchGraph(Protocol):
    """Apa pun yang bisa ditelusuri Dijkstra: cukup punya `has_stop` dan `outgoing`.

    `TransitGraph` memenuhinya, begitu juga `RequestGraph` di planner.py
    (graf dasar + node virtual titik awal/tujuan).
    """

    def has_stop(self, stop_id: str) -> bool: ...

    def outgoing(self, stop_id: str) -> list[Edge]: ...


def walk_minutes(distance_km: float, speed_kmh: float = WALK_SPEED_KMH) -> float:
    """Waktu jalan kaki (menit) untuk jarak `distance_km`."""
    return distance_km / speed_kmh * MINUTES_PER_HOUR


def load_network(path: Path) -> tuple[list[Stop], list[Edge]]:
    """Baca file JSON berisi `stops` dan `route_segments`.

    Format masih sementara (belum final dengan Anggota 1). Setiap segmen
    dianggap **satu arah**; arah sebaliknya harus ditulis sebagai segmen sendiri.
    """
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)

    stops = [
        Stop(
            id=item["id"],
            name=item["name"],
            lat=item["lat"],
            lon=item["lon"],
            modes=tuple(item.get("modes", [])),
        )
        for item in raw["stops"]
    ]
    segments = [
        Edge(
            from_stop=item["from_stop"],
            to_stop=item["to_stop"],
            mode=item["mode"],
            route_id=item["route_id"],
            distance_km=item["distance_km"],
            travel_min=item["travel_min"],
            headway_min=item["headway_min"],
        )
        for item in raw["route_segments"]
    ]
    return stops, segments


def build_walk_edges(stops: list[Stop], max_km: float) -> list[Edge]:
    """Buat edge jalan kaki dua arah untuk setiap pasangan halte berjarak <= `max_km`."""
    edges = []
    for a, b, distance in find_close_pairs(stops, max_km):
        minutes = walk_minutes(distance)
        edges.append(Edge(a.id, b.id, WALK, None, distance, minutes))
        edges.append(Edge(b.id, a.id, WALK, None, distance, minutes))
    return edges


def _krl_distances_from(
    source: str, adjacency: dict[str, list[tuple[str, float]]]
) -> dict[str, float]:
    """Jarak KRL terpendek dari `source` ke semua stasiun yang terjangkau.

    Dijkstra versi paling sederhana: state = stasiun saja, bobot = km.
    """
    distances = {source: 0.0}
    queue = [(0.0, source)]
    while queue:
        distance, stop_id = heapq.heappop(queue)
        if distance > distances[stop_id]:
            continue  # entri usang
        for next_stop, km in adjacency.get(stop_id, []):
            new_distance = distance + km
            if new_distance < distances.get(next_stop, math.inf):
                distances[next_stop] = new_distance
                heapq.heappush(queue, (new_distance, next_stop))
    return distances


def build_krl_distance_table(segments: list[Edge]) -> KrlDistanceTable:
    """Tabel jarak KRL terpendek dari setiap stasiun tempat orang bisa naik KRL.

    Dihitung sekali saat graf dibangun (jumlah stasiun KRL hanya puluhan).
    """
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for segment in segments:
        if segment.mode == "krl":
            adjacency[segment.from_stop].append((segment.to_stop, segment.distance_km))
    return {source: _krl_distances_from(source, adjacency) for source in adjacency}


def build_graph(
    stops: list[Stop],
    segments: list[Edge],
    max_walk_km: float = MAX_WALK_TRANSFER_KM,
) -> TransitGraph:
    """Gabungkan halte, segmen kendaraan, dan transfer jalan kaki menjadi satu graf.

    Graf ini cukup dibangun sekali lalu dipakai ulang untuk semua request.
    """
    stops_by_id = {stop.id: stop for stop in stops}
    for segment in segments:
        for stop_id in (segment.from_stop, segment.to_stop):
            if stop_id not in stops_by_id:
                raise ValueError(
                    f"Segmen {segment.route_id} memakai halte {stop_id!r} yang tidak ada"
                )

    edges_from: dict[str, list[Edge]] = defaultdict(list)
    for edge in segments + build_walk_edges(stops, max_walk_km):
        edges_from[edge.from_stop].append(edge)

    return TransitGraph(
        stops=stops_by_id,
        edges_from=dict(edges_from),
        krl_km_between=build_krl_distance_table(segments),
    )
