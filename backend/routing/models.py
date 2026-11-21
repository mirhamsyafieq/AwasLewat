"""Struktur data dasar mesin rute.

Semua dataclass di sini `frozen=True` (tidak bisa diubah setelah dibuat) supaya
aman dipakai sebagai kunci dict dan tidak berubah diam-diam di tengah pencarian.
"""

from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["krl", "brt", "metrotrans", "mikrotrans", "walk", "drive"]

WALK: Mode = "walk"
# Akses berkendara (ojek/mobil) dari titik awal ke halte, atau dari halte ke tujuan.
DRIVE: Mode = "drive"
# Moda tanpa kendaraan umum: tidak ada tarif, tidak ada waktu tunggu, route_id None.
NON_TRANSIT_MODES = frozenset({WALK, DRIVE})

# Koordinat dalam urutan GeoJSON: (lon, lat).
LonLat = tuple[float, float]


@dataclass(frozen=True)
class Stop:
    """Satu stasiun KRL atau halte bus."""

    id: str
    name: str
    lat: float
    lon: float
    modes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Edge:
    """Satu sisi berarah di graf: segmen kendaraan, jalan kaki, atau akses berkendara.

    Untuk jalan kaki dan akses berkendara: `route_id is None`, `headway_min == 0`.
    `geometry` = jalur jalan asli (dari OSRM) bila ada; None untuk segmen biasa.
    """

    from_stop: str
    to_stop: str
    mode: Mode
    route_id: str | None
    distance_km: float
    travel_min: float
    headway_min: float = 0.0
    geometry: tuple[LonLat, ...] | None = None


@dataclass(frozen=True)
class FareZone:
    """Area berbayar tempat penumpang sedang berada (hanya untuk kategori termurah).

    - `system == "krl"`: sudah tap-in KRL di stasiun `tap_in_stop`. Tarif KRL baru
      dibayar saat tap-out, dari jarak terpendek tap-in → tap-out.
    - `system == "tj"`: sudah bayar Transjakarta dan belum keluar halte.

    Yang disimpan stasiun tap-in, **bukan** km yang sudah ditempuh: km bisa
    bertambah tanpa batas bila rute bolak-balik di stasiun transit, sehingga
    jumlah state Dijkstra meledak. Stasiun tap-in jumlahnya terbatas.
    """

    system: Literal["krl", "tj"]
    tap_in_stop: str | None = None


@dataclass(frozen=True)
class SearchState:
    """State Dijkstra: di halte mana, sedang naik rute apa, di area berbayar apa.

    `route_id is None` berarti sedang tidak di kendaraan (baru mulai atau jalan kaki).
    `fare_zone is None` berarti di luar area berbayar.
    """

    stop_id: str
    route_id: str | None
    fare_zone: FareZone | None


@dataclass(frozen=True)
class Leg:
    """Satu bagian perjalanan: satu kali naik kendaraan, atau satu kali jalan kaki.

    `stop_ids` = semua halte yang dilewati leg ini, dari `from_stop` sampai
    `to_stop`; dipakai untuk menggambar garis bila `geometry` tidak ada.
    `geometry` = jalur jalan asli (hanya untuk leg akses dari OSRM), atau None.
    """

    mode: Mode
    route_id: str | None
    from_stop: str
    to_stop: str
    distance_km: float
    wait_min: float
    ride_min: float
    stop_ids: tuple[str, ...] = ()
    geometry: tuple[LonLat, ...] | None = None

    @property
    def duration_min(self) -> float:
        """Total waktu leg = waktu tunggu + waktu di perjalanan."""
        return self.wait_min + self.ride_min


@dataclass
class Itinerary:
    """Satu hasil rute lengkap yang dikirim ke klien."""

    legs: list[Leg]
    total_min: float
    total_fare_idr: int
    transfers: int
    badges: list[str] = field(default_factory=list)
    reroute_message: str | None = None
