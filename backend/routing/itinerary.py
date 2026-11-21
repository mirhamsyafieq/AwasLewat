"""Mengubah urutan edge hasil Dijkstra menjadi itinerary (leg, waktu, tarif)."""

from dataclasses import replace

from backend.routing.models import Edge, Itinerary, Leg, SearchState
from backend.routing.weights import (
    TripContext,
    pending_krl_fare,
    ride_minutes,
    step_fare,
    wait_minutes,
)


def _continues_last_leg(legs: list[Leg], edge: Edge) -> bool:
    """True bila edge ini lanjutan leg terakhir (rute sama, atau sama-sama jalan kaki)."""
    if not legs:
        return False
    last = legs[-1]
    return last.mode == edge.mode and last.route_id == edge.route_id


def build_itinerary(edges: list[Edge], start_stop: str, trip: TripContext) -> Itinerary:
    """Kelompokkan edge menjadi leg, lalu hitung total menit, tarif, dan transit.

    Waktu dan tarif dihitung ulang dengan fungsi yang sama dengan yang dipakai
    Dijkstra, jadi angka di itinerary selalu konsisten dengan pencarian, apa pun
    kategori yang menghasilkan rute ini.
    """
    legs: list[Leg] = []
    state = SearchState(start_stop, route_id=None, fare_zone=None)
    total_min = 0.0
    total_fare = 0

    for edge in edges:
        wait = wait_minutes(state, edge)
        ride = ride_minutes(edge, trip)
        fare, next_zone = step_fare(state, edge, trip)
        total_min += wait + ride
        total_fare += fare

        if _continues_last_leg(legs, edge):
            last = legs[-1]
            legs[-1] = replace(
                last,
                to_stop=edge.to_stop,
                distance_km=last.distance_km + edge.distance_km,
                ride_min=last.ride_min + ride,
            )
        else:
            legs.append(
                Leg(
                    mode=edge.mode,
                    route_id=edge.route_id,
                    from_stop=edge.from_stop,
                    to_stop=edge.to_stop,
                    distance_km=edge.distance_km,
                    wait_min=wait,
                    ride_min=ride,
                )
            )

        state = SearchState(edge.to_stop, edge.route_id, next_zone)

    # Rute yang berakhir masih di dalam KRL (tanpa edge keluar) tetap harus tap-out.
    total_fare += pending_krl_fare(state, trip)

    vehicle_legs = sum(1 for leg in legs if leg.route_id is not None)
    return Itinerary(
        legs=legs,
        total_min=total_min,
        total_fare_idr=total_fare,
        transfers=max(0, vehicle_legs - 1),
    )
