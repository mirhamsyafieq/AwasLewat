"""Aturan tarif KRL, Transjakarta, dan Mikrotrans.

Angka tarif tidak ditulis di tengah kode: semuanya ada di `FareConfig` dan bisa
dibaca dari file JSON (`load_fare_config`). Sumber angka: PRD AwasLewat
(Bisnis.com, Januari 2026; RRI, Juli 2026).
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FareConfig:
    """Semua angka tarif. Nilai default = aturan per November 2026."""

    krl_base_idr: int = 3_000
    krl_base_km: float = 25.0
    krl_step_idr: int = 1_000
    krl_step_km: float = 10.0

    tj_flat_idr: int = 3_500
    tj_morning_idr: int = 2_000
    tj_morning_start_hour: int = 5  # inklusif: mulai 05.00
    tj_morning_end_hour: int = 7  # eksklusif: sampai 06.59
    # Aturan transfer gratis antarkoridor belum pasti; default = gratis di halte sama.
    tj_free_transfer_same_stop: bool = True

    mikrotrans_idr: int = 0


def load_fare_config(path: Path) -> FareConfig:
    """Baca konfigurasi tarif dari file JSON. Kunci yang tidak ada memakai default."""
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    return FareConfig(**raw)


def krl_fare(distance_km: float, config: FareConfig) -> int:
    """Tarif KRL untuk satu perjalanan (tap-in sampai tap-out) sejauh `distance_km`.

    Rp3.000 untuk 25 km pertama, lalu Rp1.000 untuk setiap 10 km berikutnya.
    Sisa jarak dibulatkan ke atas: 26 km dan 35 km sama-sama Rp4.000.
    """
    extra_km = max(0.0, distance_km - config.krl_base_km)
    extra_steps = math.ceil(extra_km / config.krl_step_km)
    return config.krl_base_idr + extra_steps * config.krl_step_idr


def tj_fare(hour: int, config: FareConfig) -> int:
    """Tarif sekali naik Transjakarta (BRT/Metrotrans) pada jam `hour` (0–23)."""
    if config.tj_morning_start_hour <= hour < config.tj_morning_end_hour:
        return config.tj_morning_idr
    return config.tj_flat_idr
