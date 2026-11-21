"""Perhitungan jarak di permukaan bumi dan pencarian halte berdekatan."""

import math
from collections import defaultdict
from collections.abc import Iterable

from backend.routing.models import Stop

EARTH_RADIUS_KM = 6371.0
KM_PER_DEGREE_LAT = 111.32

CANDIDATE_RADIUS_KM = 2.0
CANDIDATE_COUNT = 3


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Jarak garis lurus (great-circle) antara dua koordinat, dalam km."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def stop_distance_km(a: Stop, b: Stop) -> float:
    """Jarak haversine antara dua halte, dalam km."""
    return haversine_km(a.lat, a.lon, b.lat, b.lon)


def nearest_stops(
    stops: Iterable[Stop],
    lat: float,
    lon: float,
    count: int = CANDIDATE_COUNT,
    radius_km: float = CANDIDATE_RADIUS_KM,
) -> list[tuple[Stop, float]]:
    """Ambil `count` halte terdekat dalam radius `radius_km` dari sebuah titik.

    Hasil berupa pasangan (halte, jarak_km), terurut dari yang paling dekat.
    Scan linear sudah cukup cepat karena hanya dipanggil 2 kali per request.
    """
    in_radius = []
    for stop in stops:
        distance = haversine_km(lat, lon, stop.lat, stop.lon)
        if distance <= radius_km:
            in_radius.append((stop, distance))

    in_radius.sort(key=lambda pair: pair[1])
    return in_radius[:count]


def _grid_cell_size_deg(stops: list[Stop], max_km: float) -> float:
    """Ukuran sel grid (derajat) yang dijamin minimal `max_km` ke segala arah.

    1 derajat lintang selalu ~111 km, tetapi 1 derajat bujur makin pendek
    menjauhi khatulistiwa (dikali cos(lintang)). Kita pakai lintang terjauh
    dari khatulistiwa agar sel tidak pernah lebih kecil dari `max_km`.
    """
    max_abs_lat = max(abs(stop.lat) for stop in stops)
    km_per_degree_lon = KM_PER_DEGREE_LAT * math.cos(math.radians(max_abs_lat))
    return max_km / km_per_degree_lon


def find_close_pairs(
    stops: list[Stop], max_km: float
) -> list[tuple[Stop, Stop, float]]:
    """Cari semua pasangan halte yang jaraknya <= `max_km`.

    Daripada membandingkan semua pasangan (O(n²)), halte dikelompokkan ke sel
    grid seukuran `max_km`. Dua halte yang berjarak <= `max_km` pasti berada di
    sel yang sama atau sel tetangga, jadi cukup cek 9 sel di sekitar tiap halte.

    Setiap pasangan dikembalikan sekali saja sebagai (a, b, jarak_km).
    """
    if not stops:
        return []

    cell_size = _grid_cell_size_deg(stops, max_km)
    grid: dict[tuple[int, int], list[Stop]] = defaultdict(list)
    for stop in stops:
        cell = (math.floor(stop.lat / cell_size), math.floor(stop.lon / cell_size))
        grid[cell].append(stop)

    pairs = []
    for (row, col), cell_stops in grid.items():
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                neighbours = grid.get((row + d_row, col + d_col), [])
                for a in cell_stops:
                    for b in neighbours:
                        # a.id < b.id: tiap pasangan hanya dihitung sekali,
                        # dan halte tidak dipasangkan dengan dirinya sendiri.
                        if a.id >= b.id:
                            continue
                        distance = stop_distance_km(a, b)
                        if distance <= max_km:
                            pairs.append((a, b, distance))
    return pairs
