"""Penggabungan hasil rute yang identik menjadi satu kartu dengan beberapa badge."""

from dataclasses import replace

from backend.routing.models import Itinerary

# Urutan tetap badge di kartu, apa pun urutan kategori dicari.
BADGE_ORDER = ("fastest", "cheapest", "fewest_transfers", "least_crowded")

RouteKey = tuple[tuple[str, str, str], ...]


def itinerary_key(itinerary: Itinerary) -> RouteKey:
    """Kunci pembanding: urutan (route_id, naik_di, turun_di) per leg kendaraan.

    Leg jalan kaki/berkendara tidak ikut, jadi dua rute yang naik-turun
    kendaraan di tempat sama dianggap rute yang sama.
    """
    return tuple(
        (leg.route_id, leg.from_stop, leg.to_stop)
        for leg in itinerary.legs
        if leg.route_id is not None
    )


def merge_duplicates(itineraries: list[Itinerary]) -> list[Itinerary]:
    """Gabungkan itinerary yang kuncinya sama; badge-nya disatukan dan diurutkan.

    Itinerary pertama untuk tiap kunci yang dipertahankan. Urutan hasil mengikuti
    urutan kemunculan pertama. List masukan tidak diubah.
    """
    merged: dict[RouteKey, Itinerary] = {}
    for itinerary in itineraries:
        key = itinerary_key(itinerary)
        if key not in merged:
            merged[key] = replace(itinerary, badges=list(itinerary.badges))
            continue
        badges = merged[key].badges
        for badge in itinerary.badges:
            if badge not in badges:
                badges.append(badge)

    for itinerary in merged.values():
        itinerary.badges.sort(key=BADGE_ORDER.index)
    return list(merged.values())
