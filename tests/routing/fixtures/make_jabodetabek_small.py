"""Generator fixture `jabodetabek_small.json` untuk test skenario.

PERHATIAN: koordinat di bawah adalah **perkiraan** (bisa meleset beberapa ratus
meter) dan jarak/waktu segmen dihitung dari haversine dengan kecepatan rata-rata.
Ini cukup untuk menguji logika mesin rute, tetapi **bukan data asli**. Sebelum
demo, cek ke OSM atau ganti dengan data pipeline dari Anggota 1.

Jalankan dari root proyek:
    python -m tests.routing.fixtures.make_jabodetabek_small
"""

import itertools
import json
from pathlib import Path

from backend.routing.geo import haversine_km

OUTPUT_PATH = Path(__file__).parent / "jabodetabek_small.json"

# Rel/jalan lebih panjang dari garis lurus antarstasiun/halte.
KRL_TRACK_FACTOR = 1.1
BRT_ROAD_FACTOR = 1.2
# Kecepatan rata-rata termasuk waktu berhenti di stasiun/halte.
KRL_AVG_SPEED_KMH = 40.0
BRT_AVG_SPEED_KMH = 20.0
MINUTES_PER_HOUR = 60

# (id, nama, lat, lon, moda)
STOPS: list[tuple[str, str, float, float, str]] = [
    # Commuter Line Bogor (Bogor → Jakarta Kota)
    ("BOO", "Bogor", -6.5953, 106.7906, "krl"),
    ("CTA", "Citayam", -6.4487, 106.8025, "krl"),
    ("DP", "Depok", -6.4049, 106.8173, "krl"),
    ("DPB", "Depok Baru", -6.3912, 106.8217, "krl"),
    ("UI", "Universitas Indonesia", -6.3608, 106.8318, "krl"),
    ("PSM", "Pasar Minggu", -6.2843, 106.8445, "krl"),
    ("TEB", "Tebet", -6.2263, 106.8583, "krl"),
    ("MRI", "Manggarai", -6.2099, 106.8502, "krl"),
    ("CKI", "Cikini", -6.1987, 106.8412, "krl"),
    ("GDD", "Gondangdia", -6.1859, 106.8325, "krl"),
    ("JUA", "Juanda", -6.1667, 106.8305, "krl"),
    ("JAKK", "Jakarta Kota", -6.1376, 106.8146, "krl"),
    # Commuter Line Cikarang (Bekasi → Manggarai → Tanah Abang)
    ("BKS", "Bekasi", -6.2361, 106.9994, "krl"),
    ("KRI", "Kranji", -6.2244, 106.9794, "krl"),
    ("CUK", "Cakung", -6.2190, 106.9520, "krl"),
    ("KLD", "Klender", -6.2135, 106.8996, "krl"),
    ("JNG", "Jatinegara", -6.2150, 106.8703, "krl"),
    ("SUD", "Sudirman", -6.2023, 106.8233, "krl"),
    ("KAT", "Karet", -6.2008, 106.8160, "krl"),
    ("THB", "Tanah Abang", -6.1857, 106.8108, "krl"),
    # Transjakarta Koridor 1 (Blok M → Kota)
    ("TJ-BLM", "Halte Blok M", -6.2433, 106.8007, "brt"),
    ("TJ-MAG", "Halte Masjid Agung", -6.2357, 106.7986, "brt"),
    ("TJ-BSN", "Halte Bundaran Senayan", -6.2273, 106.8017, "brt"),
    ("TJ-GBK", "Halte Gelora Bung Karno", -6.2240, 106.8059, "brt"),
    ("TJ-PMJ", "Halte Polda Metro Jaya", -6.2210, 106.8106, "brt"),
    ("TJ-BNH", "Halte Bendungan Hilir", -6.2152, 106.8178, "brt"),
    ("TJ-DKA", "Halte Dukuh Atas", -6.2048, 106.8226, "brt"),
    ("TJ-TSR", "Halte Tosari", -6.1971, 106.8231, "brt"),
    ("TJ-BHI", "Halte Bundaran HI", -6.1923, 106.8228, "brt"),
    ("TJ-SRN", "Halte Sarinah", -6.1876, 106.8234, "brt"),
    ("TJ-BI", "Halte Bank Indonesia", -6.1826, 106.8226, "brt"),
    ("TJ-MNS", "Halte Monas", -6.1765, 106.8228, "brt"),
    ("TJ-HRM", "Halte Harmoni", -6.1655, 106.8202, "brt"),
    ("TJ-KOT", "Halte Kota", -6.1375, 106.8133, "brt"),
]

# (line_id, moda, headway_min, urutan halte)
LINES: list[tuple[str, str, float, list[str]]] = [
    (
        "KRL-BOGOR",
        "krl",
        10.0,
        ["BOO", "CTA", "DP", "DPB", "UI", "PSM", "TEB", "MRI", "CKI", "GDD", "JUA", "JAKK"],
    ),
    (
        "KRL-CIKARANG",
        "krl",
        15.0,
        ["BKS", "KRI", "CUK", "KLD", "JNG", "MRI", "SUD", "KAT", "THB"],
    ),
    (
        "TJ-1",
        "brt",
        5.0,
        [
            "TJ-BLM", "TJ-MAG", "TJ-BSN", "TJ-GBK", "TJ-PMJ", "TJ-BNH", "TJ-DKA",
            "TJ-TSR", "TJ-BHI", "TJ-SRN", "TJ-BI", "TJ-MNS", "TJ-HRM", "TJ-KOT",
        ],
    ),
]  # fmt: skip

FACTOR_AND_SPEED = {
    "krl": (KRL_TRACK_FACTOR, KRL_AVG_SPEED_KMH),
    "brt": (BRT_ROAD_FACTOR, BRT_AVG_SPEED_KMH),
}


def _segments_for_line(
    line_id: str,
    mode: str,
    headway_min: float,
    stop_ids: list[str],
    coords: dict[str, tuple[float, float]],
) -> list[dict]:
    """Segmen dua arah. route_id dibedakan per arah (`:0` dan `:1`, seperti
    `direction_id` di GTFS) supaya putar balik tidak dianggap "tetap di kendaraan"."""
    factor, speed = FACTOR_AND_SPEED[mode]
    segments = []
    for direction, sequence in ((0, stop_ids), (1, list(reversed(stop_ids)))):
        for from_id, to_id in itertools.pairwise(sequence):
            distance = haversine_km(*coords[from_id], *coords[to_id]) * factor
            segments.append(
                {
                    "route_id": f"{line_id}:{direction}",
                    "mode": mode,
                    "from_stop": from_id,
                    "to_stop": to_id,
                    "distance_km": round(distance, 3),
                    "travel_min": round(distance / speed * MINUTES_PER_HOUR, 2),
                    "headway_min": headway_min,
                }
            )
    return segments


def build_fixture() -> dict:
    """Susun isi fixture dalam format sementara pipeline (stops + route_segments)."""
    coords = {stop_id: (lat, lon) for stop_id, _, lat, lon, _ in STOPS}
    stops = [
        {"id": stop_id, "name": name, "lat": lat, "lon": lon, "modes": [mode]}
        for stop_id, name, lat, lon, mode in STOPS
    ]
    segments = []
    for line_id, mode, headway, stop_ids in LINES:
        segments += _segments_for_line(line_id, mode, headway, stop_ids, coords)

    return {
        "_comment": (
            "Dibuat oleh make_jabodetabek_small.py. Koordinat PERKIRAAN, "
            "bukan data asli; jangan dipakai untuk demo."
        ),
        "stops": stops,
        "route_segments": segments,
    }


if __name__ == "__main__":
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(build_fixture(), file, ensure_ascii=False, indent=1)
        file.write("\n")
    print(f"Ditulis: {OUTPUT_PATH}")
