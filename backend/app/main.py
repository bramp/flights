"""FastAPI entrypoint serving the interactive Web UI and optimization API."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.data.airports import (
    AIRPORTS,
    CITY_DISTANCE_MI,
    COUNTRY_NAMES,
    METRO_GROUPS,
    get_airport,
    suggest_airports,
)
from backend.app.models.schemas import CacheStats, OptimizationResponse, ProviderMode, TripRequest
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.solver.optimizer import optimize_trip

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Multi-City Flight & Ticket Optimizer",
    version="0.1.0",
)

flight_cache = FlightCache(
    db_path="flights_cache.db",
    ttl_seconds=int(float(os.environ.get("FLIGHT_CACHE_TTL_DAYS", "7")) * 86400),
)
flight_provider = CompositeFlightProvider()


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/provider-status")
def provider_status() -> dict[str, object]:
    load_dotenv()
    has_serp = bool(os.environ.get("SERPAPI_KEY", "").strip())
    stats = flight_cache.get_stats()
    return {
        "testing_mode": os.environ.get("FARESPLIT_TESTING") == "1",
        "has_serpapi_key": has_serp,
        "total_serpapi_calls_logged": stats.total_serpapi_calls_logged,
        "cache_stats": stats,
    }


@app.get("/api/airports")
def list_airports(q: str = Query(default="", description="City, airport name, or IATA code")) -> dict[str, object]:
    return {
        "suggestions": suggest_airports(q),
        "metros": METRO_GROUPS,
        "all_airports": {
            code: {
                "code": info.code,
                "name": info.name,
                "city": info.city,
                "country": info.country,
                "country_name": COUNTRY_NAMES.get(info.country, info.country),
                "region": info.region,
                "lat": info.lat,
                "lon": info.lon,
                "metro_code": info.metro_code,
                "is_major_hub": info.is_major_hub,
                "city_distance_mi": CITY_DISTANCE_MI.get(code, 12),
                "nearby": list(info.nearby_codes),
            }
            for code, info in AIRPORTS.items()
        },
    }


@app.get("/api/airport/{code}")
def get_airport_info(code: str) -> dict[str, object]:
    info = get_airport(code)
    return {
        "code": info.code,
        "name": info.name,
        "city": info.city,
        "country": info.country,
        "region": info.region,
        "metro_code": info.metro_code,
        "nearby": [
            {
                "code": nb,
                "name": AIRPORTS[nb].name if nb in AIRPORTS else nb,
                "city": AIRPORTS[nb].city if nb in AIRPORTS else nb,
                "same_metro": (AIRPORTS[nb].metro_code == info.metro_code) if nb in AIRPORTS else False,
            }
            for nb in info.nearby_codes
        ],
    }


@app.get("/api/cache/stats", response_model=CacheStats)
def get_cache_stats() -> CacheStats:
    return flight_cache.get_stats()


@app.post("/api/cache/clear", response_model=CacheStats)
def clear_cache() -> CacheStats:
    flight_cache.clear_all()
    return flight_cache.get_stats()


@app.post("/api/optimize", response_model=OptimizationResponse)
def run_optimization(request: TripRequest) -> OptimizationResponse:
    if request.provider_mode == ProviderMode.OFFLINE and os.environ.get("FARESPLIT_TESTING") != "1":
        raise HTTPException(status_code=403, detail="Simulated flights are disabled outside testing mode.")
    try:
        return optimize_trip(request, raw_provider=flight_provider, cache=flight_cache)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
