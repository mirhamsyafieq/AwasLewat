"""Endpoint `POST /route` (router FastAPI).

Anggota 1 cukup menambahkan di `main.py`:

    from backend.routing.api import router as route_router
    app.include_router(route_router)

Graf dan klien HTTP dibuat sekali saat dipakai pertama kali (`lru_cache`), lalu
dipakai ulang oleh semua request.
"""

import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.routing.access import (
    AccessProvider,
    LiveAccessProvider,
    create_http_client,
)
from backend.routing.fares import FareConfig
from backend.routing.graph import TransitGraph, build_graph, load_network
from backend.routing.models import Itinerary, Leg, LonLat
from backend.routing.planner import DESTINATION_ID, ORIGIN_ID, Point, plan_trip
from backend.routing.tomtom import read_api_key
from backend.routing.weights import TripContext

# WIB = UTC+7 tanpa jam musim panas, jadi offset tetap sudah cukup
# (zoneinfo di Windows butuh paket tzdata tambahan).
WIB = timezone(timedelta(hours=7), name="WIB")

# Lokasi file data jaringan dari pipeline Anggota 1 (bisa diganti lewat env).
NETWORK_PATH_ENV = "AWASLEWAT_NETWORK_PATH"
DEFAULT_NETWORK_PATH = Path("data/processed/network.json")

# Nama yang ditampilkan untuk node virtual.
ORIGIN_LABEL = "origin"
DESTINATION_LABEL = "destination"
ORIGIN_NAME = "Titik awal"
DESTINATION_NAME = "Tujuan"

MINUTES_DECIMALS = 1

router = APIRouter(tags=["route"])


# --- Skema request/response ---
# TODO: ganti dengan skema bersama dari Anggota 3. `from_name`/`to_name` adalah
# usulan tambahan dari draf kontrak (supaya klien tidak perlu mencari nama halte).


class Coordinate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: Coordinate
    destination: Coordinate
    depart_at: datetime | None = None


class LineString(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[LonLat]


class LegOut(BaseModel):
    mode: str
    route_id: str | None
    from_stop: str = Field(serialization_alias="from")
    to_stop: str = Field(serialization_alias="to")
    from_name: str
    to_name: str
    duration_min: float
    geometry: LineString


class ItineraryOut(BaseModel):
    badges: list[str]
    total_min: float
    total_fare_idr: int
    transfers: int
    reroute_message: str | None
    legs: list[LegOut]


class RouteResponse(BaseModel):
    itineraries: list[ItineraryOut]


# --- Sumber daya bersama (dibuat sekali) ---


@lru_cache(maxsize=1)
def get_graph() -> TransitGraph:
    """Bangun graf dari file pipeline sekali saja, lalu simpan di memori."""
    path = Path(os.environ.get(NETWORK_PATH_ENV, str(DEFAULT_NETWORK_PATH)))
    stops, segments = load_network(path)
    return build_graph(stops, segments)


def require_graph() -> TransitGraph:
    """Dependency FastAPI: graf, atau 503 bila file data belum tersedia."""
    try:
        return get_graph()
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=503, detail="Data jaringan rute belum tersedia"
        ) from error


@lru_cache(maxsize=1)
def get_http_client() -> httpx.AsyncClient:
    """Satu klien HTTP untuk semua request (koneksi dipakai ulang)."""
    return create_http_client()


@lru_cache(maxsize=1)
def get_access_provider() -> AccessProvider:
    """Satu provider untuk semua request, supaya cache OSRM/TomTom-nya terpakai."""
    return LiveAccessProvider(get_http_client(), read_api_key())


# --- Konversi ---


def departure_hour(depart_at: datetime | None) -> int:
    """Jam keberangkatan (0–23) dalam WIB.

    Kosong = sekarang. Tanpa zona waktu = dianggap WIB.
    """
    if depart_at is None:
        return datetime.now(WIB).hour
    if depart_at.tzinfo is None:
        depart_at = depart_at.replace(tzinfo=WIB)
    return depart_at.astimezone(WIB).hour


def _point_lon_lat(
    stop_id: str, graph: TransitGraph, origin: Point, destination: Point
) -> LonLat:
    """Koordinat (lon, lat) sebuah halte atau node virtual."""
    if stop_id == ORIGIN_ID:
        return origin.lon, origin.lat
    if stop_id == DESTINATION_ID:
        return destination.lon, destination.lat
    stop = graph.stops[stop_id]
    return stop.lon, stop.lat


def _label_and_name(stop_id: str, graph: TransitGraph) -> tuple[str, str]:
    """ID dan nama untuk ditampilkan; node virtual diganti label yang mudah dibaca."""
    if stop_id == ORIGIN_ID:
        return ORIGIN_LABEL, ORIGIN_NAME
    if stop_id == DESTINATION_ID:
        return DESTINATION_LABEL, DESTINATION_NAME
    return stop_id, graph.stops[stop_id].name


def leg_geometry(
    leg: Leg, graph: TransitGraph, origin: Point, destination: Point
) -> LineString:
    """Jalur asli OSRM bila ada; selain itu garis lewat halte-halte yang dilewati.

    Bentuk jalur kendaraan yang sebenarnya menunggu data `shapes` dari Anggota 1.
    """
    if leg.geometry:
        return LineString(coordinates=list(leg.geometry))
    coordinates = [
        _point_lon_lat(stop_id, graph, origin, destination) for stop_id in leg.stop_ids
    ]
    return LineString(coordinates=coordinates)


def to_leg_out(
    leg: Leg, graph: TransitGraph, origin: Point, destination: Point
) -> LegOut:
    """Ubah `Leg` internal menjadi bentuk JSON."""
    from_label, from_name = _label_and_name(leg.from_stop, graph)
    to_label, to_name = _label_and_name(leg.to_stop, graph)
    return LegOut(
        mode=leg.mode,
        route_id=leg.route_id,
        from_stop=from_label,
        to_stop=to_label,
        from_name=from_name,
        to_name=to_name,
        duration_min=round(leg.duration_min, MINUTES_DECIMALS),
        geometry=leg_geometry(leg, graph, origin, destination),
    )


def to_itinerary_out(
    itinerary: Itinerary, graph: TransitGraph, origin: Point, destination: Point
) -> ItineraryOut:
    """Ubah `Itinerary` internal menjadi bentuk JSON."""
    return ItineraryOut(
        badges=itinerary.badges,
        total_min=round(itinerary.total_min, MINUTES_DECIMALS),
        total_fare_idr=itinerary.total_fare_idr,
        transfers=itinerary.transfers,
        reroute_message=itinerary.reroute_message,
        legs=[to_leg_out(leg, graph, origin, destination) for leg in itinerary.legs],
    )


# --- Endpoint ---


@router.post("/route", response_model=RouteResponse)
async def route(
    request: RouteRequest,
    graph: Annotated[TransitGraph, Depends(require_graph)],
    access: Annotated[AccessProvider, Depends(get_access_provider)],
) -> RouteResponse:
    """Cari rute multimoda dari titik awal ke tujuan untuk empat kategori.

    Daftar `itineraries` kosong berarti tidak ada halte dalam radius 2 km dari
    titik awal/tujuan, atau tujuan tidak terjangkau.
    """
    origin = Point(request.origin.lat, request.origin.lon)
    destination = Point(request.destination.lat, request.destination.lon)
    trip = TripContext(
        hour=departure_hour(request.depart_at),
        fare_config=FareConfig(),
        krl_km_between=graph.krl_km_between,
    )

    itineraries = await plan_trip(graph, origin, destination, trip, access)
    return RouteResponse(
        itineraries=[
            to_itinerary_out(it, graph, origin, destination) for it in itineraries
        ]
    )
