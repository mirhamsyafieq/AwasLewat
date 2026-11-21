"""Cache sederhana dengan masa berlaku (TTL) untuk hasil OSRM dan TomTom.

Tujuannya menghemat kuota API: permintaan dengan koordinat (hampir) sama dalam
rentang waktu TTL tidak dikirim ulang.
"""

import time
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

# 4 desimal ≈ 11 m. Dua titik sedekat itu dianggap sama untuk keperluan cache.
COORD_DECIMALS = 4

Clock = Callable[[], float]
V = TypeVar("V")


def round_point(lat: float, lon: float) -> tuple[float, float]:
    """Bulatkan koordinat agar titik yang sangat berdekatan memakai kunci yang sama."""
    return round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS)


class TtlCache(Generic[V]):
    """Menyimpan nilai selama `ttl_seconds`, lalu menganggapnya kedaluwarsa.

    `clock` bisa diganti di test supaya tidak perlu menunggu sungguhan.
    """

    def __init__(self, ttl_seconds: float, clock: Clock = time.monotonic) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._entries: dict[Hashable, tuple[float, V]] = {}

    def get(self, key: Hashable) -> V | None:
        """Nilai untuk `key`, atau None bila tidak ada / sudah kedaluwarsa."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self.clock() >= expires_at:
            del self._entries[key]
            return None
        return value

    def set(self, key: Hashable, value: V) -> None:
        """Simpan `value` untuk `key` selama `ttl_seconds` dari sekarang."""
        self._entries[key] = (self.clock() + self.ttl_seconds, value)
