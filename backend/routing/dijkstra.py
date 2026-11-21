"""Algoritma Dijkstra buatan sendiri dengan `heapq` (priority queue).

Node pencarian bukan sekadar halte, melainkan `SearchState`
(halte, rute yang sedang dinaiki, area berbayar). Dengan begitu waktu tunggu,
penalti transit, dan tarif bisa dihitung dengan benar: tiba di halte yang sama
sambil masih di dalam kereta berbeda dengan tiba sambil berjalan kaki.
"""

import heapq
import itertools
import math
from dataclasses import dataclass

from backend.routing.graph import SearchGraph
from backend.routing.models import Edge, SearchState
from backend.routing.weights import StepFunction


@dataclass(frozen=True)
class SearchResult:
    """Hasil pencarian: total biaya (dalam satuan kategori) dan urutan edge."""

    cost: float
    edges: list[Edge]


def _reconstruct_edges(
    came_from: dict[SearchState, tuple[SearchState, Edge]],
    goal: SearchState,
) -> list[Edge]:
    """Telusuri balik dari state tujuan ke state awal lewat `came_from`."""
    edges = []
    state = goal
    while state in came_from:
        previous, edge = came_from[state]
        edges.append(edge)
        state = previous
    edges.reverse()
    return edges


def find_path(
    graph: SearchGraph,
    start_stop: str,
    goal_stop: str,
    step: StepFunction,
) -> SearchResult | None:
    """Cari rute berbiaya minimum dari `start_stop` ke `goal_stop`.

    `step` menentukan kategori (tercepat, termurah, ...). Mengembalikan `None`
    bila tujuan tidak bisa dicapai.
    """
    for stop_id in (start_stop, goal_stop):
        if not graph.has_stop(stop_id):
            raise ValueError(f"Halte {stop_id!r} tidak ada di graf")

    start = SearchState(start_stop, route_id=None, fare_zone=None)
    best_cost: dict[SearchState, float] = {start: 0.0}
    came_from: dict[SearchState, tuple[SearchState, Edge]] = {}

    # Penghitung urutan masuk: bila dua entri biayanya sama, heapq membandingkan
    # angka ini, bukan SearchState (yang memang tidak bisa dibandingkan dengan <).
    order = itertools.count()
    queue: list[tuple[float, int, SearchState]] = [(0.0, next(order), start)]

    while queue:
        cost, _, state = heapq.heappop(queue)

        # Entri usang: state ini sudah pernah dicapai dengan biaya lebih kecil.
        if cost > best_cost[state]:
            continue

        # State pertama yang keluar dari queue di halte tujuan pasti termurah,
        # karena semua biaya langkah >= 0.
        if state.stop_id == goal_stop:
            return SearchResult(cost, _reconstruct_edges(came_from, state))

        for edge in graph.outgoing(state.stop_id):
            step_cost, next_zone = step(state, edge)
            if step_cost < 0:
                raise ValueError(
                    f"Biaya negatif pada edge {edge}; Dijkstra butuh biaya >= 0"
                )

            next_state = SearchState(edge.to_stop, edge.route_id, next_zone)
            new_cost = cost + step_cost
            if new_cost < best_cost.get(next_state, math.inf):
                best_cost[next_state] = new_cost
                came_from[next_state] = (state, edge)
                heapq.heappush(queue, (new_cost, next(order), next_state))

    return None
