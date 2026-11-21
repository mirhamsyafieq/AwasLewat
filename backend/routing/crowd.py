"""Tabel kepadatan penumpang untuk kategori "paling lengang".

PERHATIAN: angka default di bawah adalah **heuristik sementara**, bukan data.
Tabel asli (dari survei/pengamatan) disiapkan Anggota 1 dan dibaca lewat
`load_crowd_config`.

Pengali 1,0 = normal. Pengali 2,0 = terasa dua kali lebih "berat", sehingga
10 menit di kereta penuh dihitung seperti 20 menit.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

# 06.00–08.59 dan 16.00–19.59 (sama dengan jam sibuk bus di weights.py).
DEFAULT_PEAK_HOURS = frozenset({6, 7, 8, 16, 17, 18, 19})
DEFAULT_PEAK_BY_MODE = {"krl": 2.0, "brt": 1.8, "metrotrans": 1.3, "mikrotrans": 1.3}
DEFAULT_OFF_PEAK_BY_MODE = {
    "krl": 1.0,
    "brt": 1.0,
    "metrotrans": 1.0,
    "mikrotrans": 1.0,
}
# Moda yang tidak ada di tabel (jalan kaki, berkendara) tidak terpengaruh kepadatan.
NEUTRAL_MULTIPLIER = 1.0


@dataclass(frozen=True)
class CrowdConfig:
    """Pengali kepadatan per moda, dengan pengganti opsional per `route_id`.

    `route_overrides[route_id] = (pengali_jam_sibuk, pengali_di_luar_jam_sibuk)`.
    Karena `route_id` berbeda per arah, arah yang lebih padat (mis. ke Jakarta
    di pagi hari) bisa diberi angka sendiri.
    """

    peak_hours: frozenset[int] = DEFAULT_PEAK_HOURS
    peak_by_mode: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_PEAK_BY_MODE)
    )
    off_peak_by_mode: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_OFF_PEAK_BY_MODE)
    )
    route_overrides: dict[str, tuple[float, float]] = field(default_factory=dict)


def load_crowd_config(path: Path) -> CrowdConfig:
    """Baca tabel kepadatan dari file JSON."""
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    return CrowdConfig(
        peak_hours=frozenset(raw["peak_hours"]),
        peak_by_mode=raw["peak_by_mode"],
        off_peak_by_mode=raw["off_peak_by_mode"],
        route_overrides={
            route_id: (values[0], values[1])
            for route_id, values in raw.get("route_overrides", {}).items()
        },
    )


def crowd_multiplier(
    config: CrowdConfig, route_id: str | None, mode: str, hour: int
) -> float:
    """Pengali kepadatan untuk satu rute pada jam `hour`.

    Urutan pencarian: pengganti per `route_id`, lalu angka per moda, lalu 1,0.
    """
    is_peak = hour in config.peak_hours

    if route_id is not None and route_id in config.route_overrides:
        peak, off_peak = config.route_overrides[route_id]
        return peak if is_peak else off_peak

    table = config.peak_by_mode if is_peak else config.off_peak_by_mode
    return table.get(mode, NEUTRAL_MULTIPLIER)
