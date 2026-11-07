"""FastAPI entrypoint serving the interactive Web UI and optimization API."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.data.airports import (
    METRO_GROUPS,
    all_known_airports,
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
_optimize_lock = threading.Lock()
logger = logging.getLogger(__name__)
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
    known = all_known_airports()
    return {
        "suggestions": suggest_airports(q),
        "metros": METRO_GROUPS,
        "all_airports": {
            code: {
                "code": info.code,
                "name": info.name,
                "city": info.city,
                "country": info.country,
                "country_name": info.country,
                "region": info.region,
                "lat": info.lat if info.has_coordinates else None,
                "lon": info.lon if info.has_coordinates else None,
                "metro_code": info.metro_code,
                "is_major_hub": info.is_major_hub,
                "nearby": list(info.nearby_codes),
            }
            for code, info in known.items()
        },
    }


@app.get("/api/airport/{code}")
def get_airport_info(code: str) -> dict[str, object]:
    info = get_airport(code)
    known = all_known_airports()
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
                "name": known[nb].name if nb in known else nb,
                "city": known[nb].city if nb in known else nb,
                "same_metro": (known[nb].metro_code == info.metro_code) if nb in known else False,
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


def _stream_optimization_events(request: TripRequest) -> Iterator[str]:
    event_queue: queue.Queue[dict[str, object] | None] = queue.Queue()
    cancelled = threading.Event()

    def on_progress(event: dict[str, object]) -> None:
        if cancelled.is_set():
            raise InterruptedError("Client disconnected")
        event_queue.put({"type": "progress", **event})

    def worker() -> None:
        try:
            with _optimize_lock:
                result = optimize_trip(
                    request,
                    raw_provider=flight_provider,
                    cache=flight_cache,
                    progress_callback=on_progress,
                )
            event_queue.put({"type": "result", "data": result.model_dump(mode="json")})
        except InterruptedError:
            return
        except ValueError as exc:
            event_queue.put({"type": "error", "detail": str(exc)})
        except Exception:
            logger.exception("Unexpected error during streaming optimization")
            event_queue.put({"type": "error", "detail": "An internal error occurred during optimization."})
        finally:
            event_queue.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    try:
        while True:
            item = event_queue.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"
    finally:
        cancelled.set()


@app.post("/api/optimize", response_model=OptimizationResponse)
def run_optimization(request: TripRequest, raw_request: Request) -> OptimizationResponse | StreamingResponse:
    if request.provider_mode == ProviderMode.OFFLINE and os.environ.get("FARESPLIT_TESTING") != "1":
        raise HTTPException(status_code=403, detail="Simulated flights are disabled outside testing mode.")

    if raw_request.headers.get("x-stream-progress") == "1":
        return StreamingResponse(
            _stream_optimization_events(request),
            media_type="application/x-ndjson",
        )

    try:
        with _optimize_lock:
            return optimize_trip(request, raw_provider=flight_provider, cache=flight_cache)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
