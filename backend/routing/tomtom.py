"""Klien TomTom Flow Segment Data: kecepatan lalu lintas saat ini di satu titik.

API key dibaca dari environment variable `TOMTOM_API_KEY` dan **tidak pernah**
ditulis di kode. Kuota gratis sekitar 20.000 permintaan per bulan, jadi klien ini
hanya dipanggil untuk akses berkendara dan hasilnya di-cache 3 menit.
"""

import os
from typing import Any

import httpx

TOMTOM_FLOW_URL = (
    "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
)
TOMTOM_KEY_ENV = "TOMTOM_API_KEY"


def read_api_key() -> str | None:
    """API key TomTom dari environment, atau None bila belum diatur."""
    key = os.environ.get(TOMTOM_KEY_ENV, "").strip()
    return key or None


def parse_current_speed(data: dict[str, Any]) -> float | None:
    """Ambil `currentSpeed` (km/jam) dari respons, atau None bila tidak valid."""
    try:
        return float(data["flowSegmentData"]["currentSpeed"])
    except (KeyError, TypeError, ValueError):
        return None


async def fetch_current_speed(
    client: httpx.AsyncClient, lat: float, lon: float, api_key: str | None
) -> float | None:
    """Kecepatan saat ini di ruas jalan terdekat dari (lat, lon), dalam km/jam.

    Mengembalikan None bila API key tidak ada atau permintaan gagal; pemanggil
    lalu menandai akses sebagai `traffic_unknown`.
    """
    if api_key is None:
        return None
    params = {"point": f"{lat},{lon}", "unit": "KMPH", "key": api_key}
    try:
        response = await client.get(TOMTOM_FLOW_URL, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return parse_current_speed(data)
