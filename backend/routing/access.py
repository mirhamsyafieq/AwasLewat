"""Akses dari titik sembarang ke halte kandidat (dan dari halte ke tujuan).

Ada dua sumber perkiraan dengan bentuk yang sama (`AccessProvider`):
- `HaversineAccessProvider`: fallback wajib tanpa jaringan.
- `LiveAccessProvider`: OSRM (jalur jalan) + TomTom (kecepatan lalu lintas),
  dengan cache, dan otomatis jatuh ke fallback bila layanan gagal.
"""

import time
from dataclasses import dataclass, replace
from typing import Protocol

import httpx

from backend.routing.cache import Clock, TtlCache, round_point
from backend.routing.geo import haversine_km
from backend.routing.graph import MINUTES_PER_HOUR, WALK_SPEED_KMH
from backend.routing.models import DRIVE, WALK, LonLat, Mode, Stop
from backend.routing.osrm import RoadRoute, fetch_route
from backend.routing.tomtom import fetch_current_speed

# Lebih dekat dari ini → jalan kaki; lebih jauh → berkendara (ojek/mobil).
WALK_ACCESS_MAX_KM = 1.0
# Jalan sebenarnya lebih panjang dari garis lurus; dipakai bila OSRM tidak tersedia.
ROAD_DETOUR_FACTOR = 1.3
# Kecepatan berkendara bila kecepatan lalu lintas tidak diketahui.
DRIVE_FALLBACK_SPEED_KMH = 20.0
# Di bawah kecepatan ini akses dianggap macet parah (pesan pengalihan).
SEVERE_JAM_SPEED_KMH = 10.0
# Batas bawah kecepatan agar tidak membagi dengan nol bila jalan ditutup (0 km/jam).
MIN_TRAFFIC_SPEED_KMH = 1.0

# --- Layanan eksternal ---
HTTP_TIMEOUT_SECONDS = 3.0
OSRM_CACHE_TTL_SECONDS = 60 * 60  # 1 jam: jalur jalan jarang berubah
TOMTOM_CACHE_TTL_SECONDS = 3 * 60  # 3 menit: lalu lintas cepat berubah
USER_AGENT = "AwasLewat/0.1 (proyek mahasiswa)"


@dataclass(frozen=True)
class AccessEstimate:
    """Perkiraan perjalanan antara satu titik dan satu halte.

    `geometry` = jalur jalan dari OSRM dalam urutan (lon, lat), atau None bila
    memakai fallback haversine.
    """

    stop_id: str
    mode: Mode
    distance_km: float
    minutes: float
    severe_jam: bool = False
    traffic_unknown: bool = False
    geometry: tuple[LonLat, ...] | None = None


class AccessProvider(Protocol):
    """Sumber perkiraan akses. Dipakai planner tanpa peduli asalnya (API atau fallback).

    `to_stop=True`: dari titik ke halte (sisi awal).
    `to_stop=False`: dari halte ke titik (sisi tujuan).
    """

    async def estimate(
        self, lat: float, lon: float, stop: Stop, *, to_stop: bool = True
    ) -> AccessEstimate: ...


def choose_access_mode(straight_km: float) -> Mode:
    """Pilih moda akses berdasarkan jarak garis lurus ke halte."""
    if straight_km <= WALK_ACCESS_MAX_KM:
        return WALK
    return DRIVE


def minutes_at_speed(distance_km: float, speed_kmh: float) -> float:
    """Waktu tempuh (menit) untuk jarak `distance_km` pada kecepatan `speed_kmh`."""
    return distance_km / speed_kmh * MINUTES_PER_HOUR


def apply_traffic(
    estimate: AccessEstimate, current_speed_kmh: float | None
) -> AccessEstimate:
    """Hitung ulang durasi akses berkendara memakai kecepatan lalu lintas saat ini.

    - Akses jalan kaki tidak terpengaruh macet: dikembalikan apa adanya.
    - Kecepatan tidak diketahui (TomTom gagal): durasi tetap, tandai `traffic_unknown`.
    - Kecepatan diketahui: durasi = jarak / kecepatan saat ini, dan tandai
      `severe_jam` bila kecepatan < `SEVERE_JAM_SPEED_KMH`.
    """
    if estimate.mode != DRIVE:
        return estimate
    if current_speed_kmh is None:
        return replace(estimate, traffic_unknown=True)

    speed = max(current_speed_kmh, MIN_TRAFFIC_SPEED_KMH)
    return replace(
        estimate,
        minutes=minutes_at_speed(estimate.distance_km, speed),
        severe_jam=current_speed_kmh < SEVERE_JAM_SPEED_KMH,
        traffic_unknown=False,
    )


def haversine_estimate(lat: float, lon: float, stop: Stop) -> AccessEstimate:
    """Perkiraan akses tanpa jaringan: jarak haversine × 1,3, kecepatan tetap."""
    straight_km = haversine_km(lat, lon, stop.lat, stop.lon)
    road_km = straight_km * ROAD_DETOUR_FACTOR

    if choose_access_mode(straight_km) == WALK:
        return AccessEstimate(
            stop.id, WALK, road_km, minutes_at_speed(road_km, WALK_SPEED_KMH)
        )
    return AccessEstimate(
        stop.id,
        DRIVE,
        road_km,
        minutes_at_speed(road_km, DRIVE_FALLBACK_SPEED_KMH),
        traffic_unknown=True,
    )


class HaversineAccessProvider:
    """Fallback tanpa jaringan (lihat `haversine_estimate`)."""

    async def estimate(
        self, lat: float, lon: float, stop: Stop, *, to_stop: bool = True
    ) -> AccessEstimate:
        """Arah tidak berpengaruh: jarak garis lurus sama ke dua arah."""
        return haversine_estimate(lat, lon, stop)


def create_http_client() -> httpx.AsyncClient:
    """Satu klien HTTP untuk seluruh server (dibuat sekali, dipakai ulang)."""
    return httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
    )


def estimate_from_route(stop_id: str, mode: Mode, route: RoadRoute) -> AccessEstimate:
    """Ubah jalur OSRM menjadi perkiraan akses.

    Jalan kaki: pakai jarak jalan OSRM, tetapi waktunya dihitung dengan 4,5 km/jam,
    karena server demo OSRM menghitung durasi seperti mobil.
    """
    if mode == WALK:
        minutes = minutes_at_speed(route.distance_km, WALK_SPEED_KMH)
    else:
        minutes = route.duration_min
    return AccessEstimate(
        stop_id, mode, route.distance_km, minutes, geometry=route.geometry
    )


def probe_point(
    estimate: AccessEstimate, start: tuple[float, float], end: tuple[float, float]
) -> tuple[float, float]:
    """Titik (lat, lon) untuk dicek kecepatannya ke TomTom: tengah jalur akses.

    Bila ada jalur OSRM, ambil titik di tengah daftar koordinatnya; bila tidak,
    ambil titik tengah garis lurus.
    """
    if estimate.geometry:
        lon, lat = estimate.geometry[len(estimate.geometry) // 2]
        return lat, lon
    return (start[0] + end[0]) / 2, (start[1] + end[1]) / 2


class LiveAccessProvider:
    """Akses memakai OSRM + TomTom, dengan cache dan fallback otomatis.

    Aturan fallback:
    - OSRM gagal → `haversine_estimate`.
    - TomTom gagal atau API key tidak ada → durasi tetap, tandai `traffic_unknown`.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None,
        clock: Clock = time.monotonic,
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.route_cache: TtlCache[RoadRoute] = TtlCache(OSRM_CACHE_TTL_SECONDS, clock)
        self.speed_cache: TtlCache[float] = TtlCache(TOMTOM_CACHE_TTL_SECONDS, clock)

    async def estimate(
        self, lat: float, lon: float, stop: Stop, *, to_stop: bool = True
    ) -> AccessEstimate:
        """Perkiraan akses antara titik (lat, lon) dan `stop`."""
        point = (lat, lon)
        stop_point = (stop.lat, stop.lon)
        start, end = (point, stop_point) if to_stop else (stop_point, point)

        mode = choose_access_mode(haversine_km(lat, lon, stop.lat, stop.lon))
        route = await self._road_route(start, end)
        if route is None:
            estimate = haversine_estimate(lat, lon, stop)
        else:
            estimate = estimate_from_route(stop.id, mode, route)

        if estimate.mode != DRIVE:
            return estimate
        speed = await self._current_speed(probe_point(estimate, start, end))
        return apply_traffic(estimate, speed)

    async def _road_route(
        self, start: tuple[float, float], end: tuple[float, float]
    ) -> RoadRoute | None:
        """Jalur OSRM dari cache, atau minta ke OSRM bila belum ada."""
        key = (round_point(*start), round_point(*end))
        cached = self.route_cache.get(key)
        if cached is not None:
            return cached

        route = await fetch_route(self.client, start[0], start[1], end[0], end[1])
        if route is not None:  # kegagalan tidak di-cache, supaya dicoba lagi nanti
            self.route_cache.set(key, route)
        return route

    async def _current_speed(self, point: tuple[float, float]) -> float | None:
        """Kecepatan TomTom dari cache, atau minta ke TomTom bila belum ada."""
        key = round_point(*point)
        cached = self.speed_cache.get(key)
        if cached is not None:
            return cached

        speed = await fetch_current_speed(self.client, point[0], point[1], self.api_key)
        if speed is not None:
            self.speed_cache.set(key, speed)
        return speed
