"""Fungsi biaya untuk Dijkstra.

Setiap kategori dibungkus sebagai *step function*: fungsi yang menerima
(state sekarang, edge yang akan dilewati) dan mengembalikan
(biaya langkah ini, area berbayar setelah melewati edge).
Dijkstra tidak perlu tahu kategori apa yang sedang dicari; ia hanya memanggil
step function ini.
"""

from collections.abc import Callable
from dataclasses import dataclass

from backend.routing.fares import FareConfig, krl_fare, tj_fare
from backend.routing.graph import KrlDistanceTable
from backend.routing.models import (
    DRIVE,
    NON_TRANSIT_MODES,
    WALK,
    Edge,
    FareZone,
    SearchState,
)

# --- Pengali macet (asumsi sementara; nanti dibaca dari tabel Anggota 1) ---
# KRL dan BRT punya jalur sendiri (steril), jadi tidak terpengaruh macet.
# Jalan kaki tidak terpengaruh macet; durasi akses berkendara sudah memperhitungkan
# macet di access.py, jadi tidak dikali lagi di sini.
SEGREGATED_MODES = frozenset({"krl", "brt", WALK, DRIVE})
BUS_PEAK_HOURS = frozenset({6, 7, 8, 16, 17, 18, 19})
BUS_OFF_PEAK_MULTIPLIER = 1.5
BUS_PEAK_MULTIPLIER = 3.0

# --- Tarif ---
TJ_MODES = frozenset({"brt", "metrotrans"})
# Biaya termurah = rupiah × FARE_WEIGHT + menit. Selama perjalanan < 1.000 menit,
# waktu hanya menjadi tie-break dan tidak pernah mengalahkan selisih Rp1.
FARE_WEIGHT = 1_000

StepFunction = Callable[[SearchState, Edge], tuple[float, FareZone | None]]


@dataclass(frozen=True)
class TripContext:
    """Informasi perjalanan yang sama untuk semua langkah pencarian.

    `hour` = jam keberangkatan (0–23, WIB). Asumsi penyederhanaan: jam ini
    dipakai untuk seluruh perjalanan (tarif pagi TJ, pengali macet bus).
    `krl_km_between` = tabel jarak KRL terpendek dari graf
    (`TransitGraph.krl_km_between`), dipakai untuk tarif KRL saat tap-out.
    """

    hour: int
    fare_config: FareConfig
    krl_km_between: KrlDistanceTable


def is_boarding(state: SearchState, edge: Edge) -> bool:
    """True bila edge ini berarti naik kendaraan baru (naik pertama atau ganti rute)."""
    return edge.route_id is not None and state.route_id != edge.route_id


def traffic_multiplier(mode: str, hour: int) -> float:
    """Pengali waktu tempuh akibat macet untuk moda `mode` pada jam `hour`."""
    if mode in SEGREGATED_MODES:
        return 1.0
    if hour in BUS_PEAK_HOURS:
        return BUS_PEAK_MULTIPLIER
    return BUS_OFF_PEAK_MULTIPLIER


def wait_minutes(state: SearchState, edge: Edge) -> float:
    """Waktu tunggu rata-rata = setengah headway, hanya saat naik kendaraan baru."""
    if is_boarding(state, edge):
        return edge.headway_min / 2
    return 0.0


def ride_minutes(edge: Edge, trip: TripContext) -> float:
    """Waktu di perjalanan untuk satu edge, sudah dikali pengali macet."""
    return edge.travel_min * traffic_multiplier(edge.mode, trip.hour)


def step_minutes(state: SearchState, edge: Edge, trip: TripContext) -> float:
    """Total menit untuk melewati satu edge: tunggu (bila naik) + perjalanan."""
    return wait_minutes(state, edge) + ride_minutes(edge, trip)


def pending_krl_fare(state: SearchState, trip: TripContext) -> int:
    """Tarif KRL yang harus dibayar bila penumpang tap-out di halte `state` sekarang.

    Rp0 bila penumpang tidak sedang di dalam area KRL. Tarif dihitung dari jarak
    KRL terpendek stasiun tap-in → stasiun ini (seperti cara KRL menghitung tarif),
    bukan dari panjang jalur yang benar-benar ditempuh.
    """
    zone = state.fare_zone
    if zone is None or zone.system != "krl" or zone.tap_in_stop is None:
        return 0
    km = trip.krl_km_between[zone.tap_in_stop][state.stop_id]
    return krl_fare(km, trip.fare_config)


def _tj_step_fare(
    state: SearchState, edge: Edge, trip: TripContext
) -> tuple[int, FareZone]:
    """Tarif tambahan Transjakarta (BRT/Metrotrans) untuk satu edge."""
    zone = state.fare_zone
    already_paid = zone is not None and zone.system == "tj"
    staying_on_bus = state.route_id == edge.route_id
    free_transfer = trip.fare_config.tj_free_transfer_same_stop

    if already_paid and (staying_on_bus or free_transfer):
        return 0, FareZone("tj")
    return tj_fare(trip.hour, trip.fare_config), FareZone("tj")


def step_fare(
    state: SearchState, edge: Edge, trip: TripContext
) -> tuple[int, FareZone | None]:
    """Rupiah yang dibayar saat melewati `edge`, dan area berbayar sesudahnya.

    KRL: naik = tap-in (Rp0 dulu); selama tetap di KRL, termasuk ganti jalur di
    stasiun yang sama, Rp0. Tarif KRL baru ditagih saat edge berikutnya bukan KRL
    (tap-out). Dengan begitu biaya per langkah tidak pernah negatif.
    """
    zone = state.fare_zone
    in_krl = zone is not None and zone.system == "krl"

    if edge.mode == "krl":
        if in_krl:
            return 0, zone
        return 0, FareZone("krl", tap_in_stop=state.stop_id)

    # Edge bukan KRL: bila tadi masih di dalam KRL, berarti tap-out di sini.
    exit_fare = pending_krl_fare(state, trip)
    rupiah, next_zone = _non_krl_step_fare(state, edge, trip)
    return exit_fare + rupiah, next_zone


def _non_krl_step_fare(
    state: SearchState, edge: Edge, trip: TripContext
) -> tuple[int, FareZone | None]:
    """Tarif untuk edge jalan kaki, berkendara, Transjakarta, atau Mikrotrans."""
    if edge.mode in NON_TRANSIT_MODES:
        # Jalan kaki atau berkendara berarti keluar dari stasiun/halte.
        return 0, None
    if edge.mode in TJ_MODES:
        return _tj_step_fare(state, edge, trip)
    # Mikrotrans: bayar (Rp0) hanya saat naik; tidak membuka area berbayar.
    if is_boarding(state, edge):
        return trip.fare_config.mikrotrans_idr, None
    return 0, None


def fastest_step(trip: TripContext) -> StepFunction:
    """Step function kategori tercepat: biaya = menit."""

    def step(state: SearchState, edge: Edge) -> tuple[float, FareZone | None]:
        return step_minutes(state, edge, trip), None

    return step


def cheapest_step(trip: TripContext) -> StepFunction:
    """Step function kategori termurah: biaya = rupiah × FARE_WEIGHT + menit.

    Catatan: tarif KRL ditagih saat tap-out, jadi pencarian harus berakhir dengan
    edge non-KRL. Planner selalu begitu (edge terakhir menuju `__destination__`).
    """

    def step(state: SearchState, edge: Edge) -> tuple[float, FareZone | None]:
        rupiah, zone = step_fare(state, edge, trip)
        return rupiah * FARE_WEIGHT + step_minutes(state, edge, trip), zone

    return step
