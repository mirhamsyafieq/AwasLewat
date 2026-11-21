"""Test klien TomTom dengan httpx.MockTransport (tanpa jaringan, tanpa key asli)."""

import asyncio

import httpx
import pytest

from backend.routing.tomtom import (
    TOMTOM_KEY_ENV,
    fetch_current_speed,
    parse_current_speed,
    read_api_key,
)

FAKE_KEY = "kunci-test"


def _fetch(transport: httpx.MockTransport, api_key: str | None) -> float | None:
    async def run() -> float | None:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_current_speed(client, -6.2, 106.8, api_key)

    return asyncio.run(run())


def test_read_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOMTOM_KEY_ENV, FAKE_KEY)
    assert read_api_key() == FAKE_KEY
    monkeypatch.setenv(TOMTOM_KEY_ENV, "   ")
    assert read_api_key() is None
    monkeypatch.delenv(TOMTOM_KEY_ENV)
    assert read_api_key() is None


def test_parse_current_speed() -> None:
    assert parse_current_speed({"flowSegmentData": {"currentSpeed": 23}}) == 23.0
    assert parse_current_speed({}) is None


def test_no_key_sends_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("tidak boleh ada permintaan tanpa API key")

    assert _fetch(httpx.MockTransport(handler), api_key=None) is None


def test_fetch_success() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"flowSegmentData": {"currentSpeed": 7}})

    assert _fetch(httpx.MockTransport(handler), FAKE_KEY) == 7.0
    assert seen[0].url.params["point"] == "-6.2,106.8"
    assert seen[0].url.params["key"] == FAKE_KEY


def test_fetch_forbidden_returns_none() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    assert _fetch(transport, FAKE_KEY) is None


def test_fetch_timeout_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    assert _fetch(httpx.MockTransport(handler), FAKE_KEY) is None
