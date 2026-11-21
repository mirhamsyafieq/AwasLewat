"""Test klien OSRM dengan httpx.MockTransport (tanpa jaringan)."""

import asyncio

import httpx
import pytest

from backend.routing.osrm import (
    OSRM_PROFILE,
    RoadRoute,
    build_route_url,
    fetch_route,
    parse_route,
)

OK_BODY = {
    "code": "Ok",
    "routes": [
        {
            "distance": 1500.0,
            "duration": 240.0,
            "geometry": {
                "type": "LineString",
                "coordinates": [[106.80, -6.20], [106.805, -6.201], [106.81, -6.20]],
            },
        }
    ],
}


def _fetch(handler: httpx.MockTransport) -> RoadRoute | None:
    async def run() -> RoadRoute | None:
        async with httpx.AsyncClient(transport=handler) as client:
            return await fetch_route(client, -6.20, 106.80, -6.20, 106.81)

    return asyncio.run(run())


def test_url_uses_lon_lat_order() -> None:
    url = build_route_url(-6.20, 106.80, -6.21, 106.81)
    assert url.endswith(f"/route/v1/{OSRM_PROFILE}/106.8,-6.2;106.81,-6.21")


def test_parse_route() -> None:
    route = parse_route(OK_BODY)
    assert route is not None
    assert route.distance_km == pytest.approx(1.5)
    assert route.duration_min == pytest.approx(4.0)
    assert route.geometry[0] == (106.80, -6.20)


@pytest.mark.parametrize(
    "body",
    [{"code": "NoRoute", "routes": []}, {}, {"code": "Ok", "routes": [{}]}],
)
def test_parse_invalid_returns_none(body: dict) -> None:
    assert parse_route(body) is None


def test_fetch_success_sends_expected_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=OK_BODY)

    route = _fetch(httpx.MockTransport(handler))
    assert route is not None
    assert route.distance_km == pytest.approx(1.5)
    assert seen[0].url.params["geometries"] == "geojson"


def test_fetch_server_error_returns_none() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    assert _fetch(transport) is None


def test_fetch_network_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    assert _fetch(httpx.MockTransport(handler)) is None


def test_fetch_invalid_json_returns_none() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))
    assert _fetch(transport) is None
