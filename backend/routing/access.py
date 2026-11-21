"""Akses dari titik sembarang ke halte kandidat (dan dari halte ke tujuan).

Saat ini baru ada `HaversineAccessProvider`, yaitu aturan **fallback wajib**
yang tidak butuh jaringan. Klien OSRM + TomTom (httpx async + cache) menyusul;
klien itu cukup mengembalikan `AccessEstimate` yang sama, lalu memakai
`apply_traffic` untuk kecepatan dari TomTom.
"""

from dataclasses import dataclass, replace
from typing import Protocol

from backend.routing.geo import haversine_km
from backend.routing.graph import MINUTES_PER_HOUR, WALK_SPEED_KMH
from backend.routing.models import DRIVE, WALK, Mode, Stop

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


@dataclass(frozen=True)
class AccessEstimate:
    """Perkiraan perjalanan antara satu titik dan satu halte."""

    stop_id: str
    mode: Mode
    distance_km: float
    minutes: float
    severe_jam: bool = False
    traffic_unknown: bool = False


class AccessProvider(Protocol):
    """Sumber perkiraan akses. Dipakai planner tanpa peduli asalnya (API atau fallback)."""

    def estimate(self, lat: float, lon: float, stop: Stop) -> AccessEstimate: ...


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


class HaversineAccessProvider:
    """Fallback tanpa jaringan: jarak haversine × 1,3 dengan kecepatan tetap."""

    def estimate(self, lat: float, lon: float, stop: Stop) -> AccessEstimate:
        """Perkiraan akses antara titik (lat, lon) dan `stop`."""
        straight_km = haversine_km(lat, lon, stop.lat, stop.lon)
        road_km = straight_km * ROAD_DETOUR_FACTOR
        mode = choose_access_mode(straight_km)

        if mode == WALK:
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
