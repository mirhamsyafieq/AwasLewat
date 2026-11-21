"""Test LiveAccessProvider: OSRM + TomTom + cache + fallback, tanpa jaringan."""

import asyncio

import httpx
import pytest

from backend.routing.access import (
    OSRM_CACHE_TTL_SECONDS,
    TOMTOM_CACHE_TTL_SECONDS,
    AccessEstimate,
    LiveAccessProvider,
    haversine_estimate,
    minutes_at_speed,
)
from backend.routing.graph import WALK_SPEED_KMH
from backend.routing.models import DRIVE, WALK, Stop

STOP = Stop("S", "Halte S", -6.2000, 106.8000)
NEAR_POINT = (-6.2000, 106.8050)  # ~0,55 km → jalan kaki
FAR_POINT = (-6.2000, 106.8150)  # ~1,7 km → berkendara
FAKE_KEY = "kunci-test"
OSRM_HOST = "router.project-osrm.org"
TOMTOM_HOST = "api.tomtom.com"
GEOMETRY = [[106.815, -6.2], [106.81, -6.199], [106.80, -6.2]]


class FakeServices:
    """Server OSRM dan TomTom palsu yang mencatat setiap permintaan."""

    def __init__(
        self,
        osrm_status: int = 200,
        distance_m: float = 2500.0,
        duration_s: float = 300.0,
        speed_kmh: float = 30.0,
    ) -> None:
        self.osrm_status = osrm_status
        self.distance_m = distance_m
        self.duration_s = duration_s
        self.speed_kmh = speed_kmh
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == OSRM_HOST:
            body = {
                "code": "Ok",
                "routes": [
                    {
                        "distance": self.distance_m,
                        "duration": self.duration_s,
                        "geometry": {"type": "LineString", "coordinates": GEOMETRY},
                    }
                ],
            }
            return httpx.Response(self.osrm_status, json=body)
        return httpx.Response(
            200, json={"flowSegmentData": {"currentSpeed": self.speed_kmh}}
        )

    def count(self, host: str) -> int:
        return sum(1 for request in self.requests if request.url.host == host)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _estimate(
    services: FakeServices,
    point: tuple[float, float],
    *,
    api_key: str | None = FAKE_KEY,
    to_stop: bool = True,
) -> AccessEstimate:
    async def run() -> AccessEstimate:
        transport = httpx.MockTransport(services)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = LiveAccessProvider(client, api_key)
            return await provider.estimate(*point, STOP, to_stop=to_stop)

    return asyncio.run(run())


def test_walk_uses_osrm_distance_and_walking_speed() -> None:
    services = FakeServices(distance_m=800.0, duration_s=60.0)
    estimate = _estimate(services, NEAR_POINT)

    assert estimate.mode == WALK
    assert estimate.distance_km == pytest.approx(0.8)
    # Durasi OSRM (60 detik, versi mobil) diabaikan untuk jalan kaki.
    assert estimate.minutes == pytest.approx(minutes_at_speed(0.8, WALK_SPEED_KMH))
    assert estimate.geometry is not None
    assert services.count(TOMTOM_HOST) == 0  # jalan kaki tidak cek lalu lintas


def test_drive_with_severe_jam() -> None:
    services = FakeServices(distance_m=2500.0, speed_kmh=5.0)
    estimate = _estimate(services, FAR_POINT)

    assert estimate.mode == DRIVE
    assert estimate.minutes == pytest.approx(30.0)  # 2,5 km / 5 km/jam
    assert estimate.severe_jam
    # Titik yang dicek ke TomTom = koordinat tengah jalur OSRM (lat, lon).
    tomtom_request = next(r for r in services.requests if r.url.host == TOMTOM_HOST)
    assert tomtom_request.url.params["point"] == "-6.199,106.81"


def test_drive_without_api_key_keeps_osrm_duration() -> None:
    services = FakeServices(duration_s=300.0)
    estimate = _estimate(services, FAR_POINT, api_key=None)

    assert estimate.minutes == pytest.approx(5.0)
    assert estimate.traffic_unknown
    assert services.count(TOMTOM_HOST) == 0


def test_osrm_failure_falls_back_to_haversine() -> None:
    services = FakeServices(osrm_status=503, speed_kmh=30.0)
    estimate = _estimate(services, FAR_POINT)

    fallback = haversine_estimate(*FAR_POINT, STOP)
    assert estimate.distance_km == pytest.approx(fallback.distance_km)
    assert estimate.geometry is None
    # TomTom tetap dipakai walau OSRM gagal.
    assert estimate.minutes == pytest.approx(
        minutes_at_speed(fallback.distance_km, 30.0)
    )


def test_destination_side_routes_from_stop_to_point() -> None:
    services = FakeServices()
    _estimate(services, FAR_POINT, to_stop=False)

    osrm_request = next(r for r in services.requests if r.url.host == OSRM_HOST)
    # Koordinat pertama di URL OSRM = titik awal = halte (lon,lat).
    assert "/106.8,-6.2;106.815,-6.2" in osrm_request.url.path


def test_results_are_cached_until_ttl() -> None:
    services = FakeServices()
    clock = FakeClock()

    async def run() -> None:
        transport = httpx.MockTransport(services)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = LiveAccessProvider(client, FAKE_KEY, clock)
            await provider.estimate(*FAR_POINT, STOP)
            await provider.estimate(*FAR_POINT, STOP)
            assert services.count(OSRM_HOST) == 1
            assert services.count(TOMTOM_HOST) == 1

            clock.now += TOMTOM_CACHE_TTL_SECONDS  # TomTom kedaluwarsa, OSRM belum
            await provider.estimate(*FAR_POINT, STOP)
            assert services.count(OSRM_HOST) == 1
            assert services.count(TOMTOM_HOST) == 2

            clock.now += OSRM_CACHE_TTL_SECONDS
            await provider.estimate(*FAR_POINT, STOP)
            assert services.count(OSRM_HOST) == 2

    asyncio.run(run())
