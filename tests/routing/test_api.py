"""Test endpoint POST /route dengan TestClient (tanpa jaringan).

Router dipasang ke aplikasi FastAPI kecil khusus test, karena `main.py` milik
Anggota 1. Graf diganti fixture Jabodetabek dan akses diganti fallback haversine
lewat `dependency_overrides`.
"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routing import api
from backend.routing.access import HaversineAccessProvider
from backend.routing.graph import TransitGraph, build_graph, load_network

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jabodetabek_small.json"
DEPOK = {"lat": -6.3920, "lon": 106.8230}
MONAS = {"lat": -6.1754, "lon": 106.8272}
BEKASI = {"lat": -6.2380, "lon": 107.0010}
BLOK_M = {"lat": -6.2440, "lon": 106.7990}
MIDDLE_OF_SEA = {"lat": -5.90, "lon": 106.80}


@pytest.fixture(scope="module")
def graph() -> TransitGraph:
    return build_graph(*load_network(FIXTURE_PATH))


@pytest.fixture
def client(graph: TransitGraph) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_graph] = lambda: graph
    app.dependency_overrides[api.get_access_provider] = HaversineAccessProvider
    return TestClient(app)


def _post(client: TestClient, origin: dict, destination: dict, **extra) -> dict:
    response = client.post(
        "/route", json={"origin": origin, "destination": destination, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_route_returns_itineraries(client: TestClient) -> None:
    body = _post(client, DEPOK, MONAS, depart_at="2026-12-01T10:00:00")
    itineraries = body["itineraries"]
    assert itineraries

    first = itineraries[0]
    assert set(first) == {
        "badges",
        "total_min",
        "total_fare_idr",
        "transfers",
        "reroute_message",
        "legs",
    }
    legs = first["legs"]
    assert legs[0]["from"] == "origin"
    assert legs[0]["from_name"] == "Titik awal"
    assert legs[-1]["to"] == "destination"
    for leg in legs:
        assert leg["geometry"]["type"] == "LineString"
        assert len(leg["geometry"]["coordinates"]) >= 2


def test_vehicle_leg_geometry_follows_stops(
    client: TestClient, graph: TransitGraph
) -> None:
    body = _post(client, DEPOK, MONAS, depart_at="2026-12-01T10:00:00")
    krl_leg = next(
        leg for leg in body["itineraries"][0]["legs"] if leg["mode"] == "krl"
    )
    start = graph.stops[krl_leg["from"]]
    coordinates = krl_leg["geometry"]["coordinates"]
    # GeoJSON memakai urutan [lon, lat]; garis melewati setiap stasiun antara.
    assert coordinates[0] == [start.lon, start.lat]
    assert len(coordinates) > 2


def test_morning_tj_fare_from_depart_at(client: TestClient) -> None:
    # Bekasi → Blok M memakai KRL + satu kali naik Transjakarta.
    morning = _post(client, BEKASI, BLOK_M, depart_at="2026-12-01T06:30:00")
    midday = _post(client, BEKASI, BLOK_M, depart_at="2026-12-01T10:00:00")
    morning_fare = morning["itineraries"][0]["total_fare_idr"]
    midday_fare = midday["itineraries"][0]["total_fare_idr"]
    assert midday_fare - morning_fare == 3_500 - 2_000


def test_no_stop_nearby_returns_empty_list(client: TestClient) -> None:
    assert _post(client, MIDDLE_OF_SEA, MONAS) == {"itineraries": []}


@pytest.mark.parametrize(
    "bad_origin",
    [{"lat": 100.0, "lon": 106.8}, {"lat": -6.2}, {"lat": "jauh", "lon": 106.8}],
)
def test_invalid_coordinates_rejected(client: TestClient, bad_origin: dict) -> None:
    response = client.post("/route", json={"origin": bad_origin, "destination": MONAS})
    assert response.status_code == 422


def test_missing_network_file_returns_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(api.NETWORK_PATH_ENV, str(tmp_path / "tidak-ada.json"))
    api.get_graph.cache_clear()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_access_provider] = HaversineAccessProvider

    response = TestClient(app).post(
        "/route", json={"origin": DEPOK, "destination": MONAS}
    )
    api.get_graph.cache_clear()
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("depart_at", "expected_hour"),
    [
        (datetime(2026, 12, 1, 6, 30), 6),  # tanpa zona waktu → WIB
        (datetime(2026, 12, 1, 0, 30, tzinfo=UTC), 7),  # 00.30 UTC
        (datetime(2026, 12, 1, 8, 0, tzinfo=timezone(timedelta(hours=8))), 7),  # WITA
    ],
)
def test_departure_hour_in_wib(depart_at: datetime, expected_hour: int) -> None:
    assert api.departure_hour(depart_at) == expected_hour


def test_departure_hour_defaults_to_now() -> None:
    assert api.departure_hour(None) == datetime.now(api.WIB).hour
