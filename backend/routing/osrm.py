"""Klien OSRM: jarak, durasi, dan jalur jalan antara dua titik.

Server demo publik OSRM **hanya mendukung profil mobil** (`driving`). Untuk akses
jalan kaki, yang dipakai hanya jarak jalannya; waktu jalan kaki dihitung sendiri
di access.py dengan kecepatan 4,5 km/jam.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from backend.routing.models import LonLat

OSRM_BASE_URL = "https://router.project-osrm.org"
OSRM_PROFILE = "driving"
METERS_PER_KM = 1000
SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class RoadRoute:
    """Satu jalur jalan hasil OSRM."""

    distance_km: float
    duration_min: float
    geometry: tuple[LonLat, ...]


def build_route_url(
    from_lat: float, from_lon: float, to_lat: float, to_lon: float
) -> str:
    """URL OSRM `route`. Perhatikan: OSRM memakai urutan lon,lat."""
    coordinates = f"{from_lon},{from_lat};{to_lon},{to_lat}"
    return f"{OSRM_BASE_URL}/route/v1/{OSRM_PROFILE}/{coordinates}"


def parse_route(data: dict[str, Any]) -> RoadRoute | None:
    """Ambil rute pertama dari respons OSRM, atau None bila respons tidak valid."""
    try:
        if data["code"] != "Ok" or not data["routes"]:
            return None
        route = data["routes"][0]
        geometry = tuple((lon, lat) for lon, lat in route["geometry"]["coordinates"])
        return RoadRoute(
            distance_km=route["distance"] / METERS_PER_KM,
            duration_min=route["duration"] / SECONDS_PER_MINUTE,
            geometry=geometry,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def fetch_route(
    client: httpx.AsyncClient,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> RoadRoute | None:
    """Minta jalur jalan ke OSRM. Mengembalikan None bila gagal (timeout, error, dll.)."""
    url = build_route_url(from_lat, from_lon, to_lat, to_lon)
    params = {"overview": "simplified", "geometries": "geojson"}
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return parse_route(data)
