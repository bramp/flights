"""FastAPI endpoint integration tests."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.main import create_app
from backend.app.models.queries import LegSearch
from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.providers.pricing_engine import RealisticPricingProvider


@pytest.fixture
def flight_provider() -> CompositeFlightProvider:
    return CompositeFlightProvider(rate_limit_seconds=0)


@pytest.fixture
def client(tmp_path: Path, flight_provider: CompositeFlightProvider) -> Iterator[TestClient]:
    application = create_app(cache=FlightCache(tmp_path / "flights.db"), provider=flight_provider)
    with TestClient(application) as test_client:
        yield test_client


def test_app_initializes_default_cache_only_on_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    application = create_app()
    assert not (tmp_path / "flights_cache.db").exists()
    with TestClient(application) as test_client:
        assert test_client.get("/api/health").status_code == 200
        assert (tmp_path / "flights_cache.db").exists()


def test_app_instances_have_independent_caches(tmp_path: Path) -> None:
    first_cache = FlightCache(tmp_path / "first.db")
    second_cache = FlightCache(tmp_path / "second.db")
    first_cache.session_hits = 1
    second_cache.session_hits = 2
    with TestClient(create_app(cache=first_cache)) as first, TestClient(create_app(cache=second_cache)) as second:
        assert first.get("/api/cache/stats").json()["cache_hits"] == 1
        assert second.get("/api/cache/stats").json()["cache_hits"] == 2
        assert first.post("/api/cache/clear").json()["cache_hits"] == 0
        assert second.get("/api/cache/stats").json()["cache_hits"] == 2


def test_health_and_airports_endpoints(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    airports_resp = client.get("/api/airports?q=London")
    assert airports_resp.status_code == 200
    data = airports_resp.json()
    assert any(item["code"] == "LHR" for item in data["suggestions"])
    assert data["all_airports"]["LHR"]["country_name"] == "GB"

    airport_resp = client.get("/api/airport/LHR")
    assert airport_resp.status_code == 200
    assert airport_resp.json()["code"] == "LHR"


def test_simulation_is_testing_only_and_never_cached(
    client: TestClient, flight_provider: CompositeFlightProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FARESPLIT_TESTING", "1")
    assert client.get("/api/provider-status").json()["testing_mode"] is True
    client.post("/api/cache/clear")

    payload = {
        "origin_label": "San Francisco",
        "origin_airports": ["SFO"],
        "destination_label": "San Francisco",
        "destination_airports": ["SFO"],
        "earliest_departure": "2026-11-10",
        "latest_departure": "2026-11-12",
        "earliest_return": "2026-11-19",
        "latest_return": "2026-11-22",
        "return_leg_cabin": "auto",
        "ordering_mode": "flexible",
        "stops": [
            {
                "id": "stop-lon",
                "label": "London",
                "airports": ["LHR", "LGW"],
                "earliest_arrival": "2026-11-10",
                "latest_departure": "2026-11-16",
                "min_nights": 3,
                "max_nights": 5,
                "fixed_order": True,
                "outbound_cabin": "auto",
            },
            {
                "id": "stop-par",
                "label": "Paris",
                "airports": ["CDG", "ORY"],
                "earliest_arrival": "2026-11-13",
                "latest_departure": "2026-11-22",
                "min_nights": 3,
                "max_nights": 5,
                "fixed_order": False,
                "outbound_cabin": "economy",
            },
        ],
        "baggage": {"include_carry_on": True, "checked_bags": 1},
        "cabin_policy": {
            "default_cabin": "economy",
            "long_haul_cabin": "business",
            "long_haul_threshold_hours": 6.5,
        },
        "weights": {
            "value_of_time_per_hour": 35.0,
            "protected_transfer_penalty": 45.0,
            "self_transfer_penalty": 140.0,
            "separate_ticket_penalty": 20.0,
            "enable_hub_splitting": True,
        },
        "provider_mode": "offline",
        "force_refresh": False,
    }

    r1 = client.post("/api/optimize", json=payload)
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["api_version"] == 2
    assert body1["recommended"]["total_price_usd"] > 0
    assert len(body1["strategy_comparison"]) >= 4
    assert body1["cache_stats"]["total_cached_flights_in_db"] == 0
    assert body1["recommended"]["tickets"][0]["fare_estimate"]["provenance"] == "estimated"
    assert any("simulated" in warning for warning in body1["warnings"])

    r2 = client.post("/api/optimize", json=payload)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["cache_stats"]["cache_misses"] == 0
    assert body2["cache_stats"]["cache_hits"] == 0
    assert body2["cache_stats"]["total_cached_flights_in_db"] == 0
    assert body2["recommended"]["tickets"][0]["fare_estimate"]["assumptions"]

    monkeypatch.delenv("FARESPLIT_TESTING")
    assert client.get("/api/provider-status").json()["testing_mode"] is False
    rejected = client.post("/api/optimize", json=payload)
    assert rejected.status_code == 403
    assert "disabled" in rejected.json()["detail"]

    monkeypatch.setattr(flight_provider, "_search_fast_flights", lambda *_args: [])
    monkeypatch.setattr(flight_provider, "_search_serpapi_google_flights", lambda *_args: [])
    payload["provider_mode"] = "auto"
    failed_live = client.post("/api/optimize", json=payload)
    assert failed_live.status_code == 400
    assert "No valid flight combinations" in failed_live.json()["detail"]


def test_optimize_rejects_degenerate_same_airport_stop(client: TestClient) -> None:
    bad_payload = {
        "origin_label": "San Francisco",
        "origin_airports": ["SFO"],
        "destination_label": "San Francisco",
        "destination_airports": ["SFO"],
        "earliest_departure": "2026-11-10",
        "latest_return": "2026-11-15",
        "stops": [
            {
                "id": "stop-same",
                "label": "San Francisco",
                "airports": ["SFO"],
                "min_nights": 3,
                "max_nights": 4,
            }
        ],
    }
    resp = client.post("/api/optimize", json=bad_payload)
    assert resp.status_code == 400
    assert "No valid flight combinations" in resp.json()["detail"]

    stream_resp = client.post("/api/optimize", json=bad_payload, headers={"X-Stream-Progress": "1"})
    assert stream_resp.status_code == 200
    stream_events = [json.loads(line) for line in stream_resp.text.splitlines() if line.strip()]
    error_events = [e for e in stream_events if e["type"] == "error"]
    assert len(error_events) == 1
    assert "No valid flight combinations" in error_events[0]["detail"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("fallback_available", [False, True])
def test_repeated_optimization_handles_unpriced_and_missing_result_groups(
    client: TestClient,
    flight_provider: CompositeFlightProvider,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fast_flights_html: Callable[[object], str],
    fast_flights_unpriced_html: str,
    stream: bool,
    fallback_available: bool,
) -> None:
    monkeypatch.setenv("SERPAPI_KEY", "test-key" if fallback_available else "")
    current_html = fast_flights_unpriced_html
    fetched: list[str] = []

    def fetch(*_args: object, **_kwargs: object) -> str:
        fetched.append(current_html)
        return current_html

    def recover(origin: str, destination: str, departure: date, cabin: ConcreteCabinClass) -> list[FlightLegOption]:
        options = RealisticPricingProvider().search(LegSearch.single(origin, destination, departure, cabin)).options
        return [option.model_copy(update={"provider": "serpapi"}) for option in options]

    monkeypatch.setattr("backend.app.providers.google_flights.fetch_flights_html", fetch)
    monkeypatch.setattr(flight_provider, "_search_serpapi_google_flights", recover)
    # Successful fallback results are cached; failed searches must retry without force refresh.
    payload = {
        "origin_airports": ["SFO"],
        "destination_airports": ["SFO"],
        "earliest_departure": "2026-12-11",
        "latest_departure": "2026-12-11",
        "earliest_return": "2026-12-15",
        "latest_return": "2026-12-15",
        "stops": [{"id": "london", "label": "London", "airports": ["LHR"], "min_nights": 4, "max_nights": 4}],
        "weights": {"enable_hub_splitting": False},
        "provider_mode": "auto",
        "force_refresh": fallback_available,
    }
    for html in (current_html, fast_flights_html(None)):
        current_html = html
        previous_calls = len(fetched)
        response = client.post("/api/optimize", json=payload, headers={"X-Stream-Progress": "1"} if stream else {})
        if stream:
            assert response.status_code == 200
            events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
            assert events[-1]["type"] == ("result" if fallback_available else "error")
            body = events[-1]["data"] if fallback_available else events[-1]
        else:
            assert response.status_code == (200 if fallback_available else 400)
            body = response.json()
        if fallback_available:
            assert body["api_version"] == 2
            assert body["recommended"]["total_price_usd"] > 0
            assert all(leg["provider"] == "serpapi" for leg in body["recommended"]["legs"])
            assert not any("fast-flights" in warning for warning in body.get("warnings", []))
        else:
            assert "No valid flight combinations" in body["detail"]
            assert "An internal error" not in body["detail"]
        assert len(fetched) > previous_calls
        assert "unable to parse response" not in response.text
    assert "Unexpected error during streaming optimization" not in caplog.text


def test_optimize_streams_progress_events_and_final_result(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FARESPLIT_TESTING", "1")
    payload = {
        "origin_label": "San Francisco",
        "origin_airports": ["SFO"],
        "destination_label": "San Francisco",
        "destination_airports": ["SFO"],
        "earliest_departure": "2026-11-10",
        "latest_departure": "2026-11-11",
        "earliest_return": "2026-11-18",
        "latest_return": "2026-11-19",
        "return_leg_cabin": "auto",
        "ordering_mode": "fixed",
        "stops": [
            {
                "id": "stop-lon",
                "label": "London",
                "airports": ["LHR"],
                "earliest_arrival": "2026-11-10",
                "latest_departure": "2026-11-15",
                "min_nights": 4,
                "max_nights": 4,
                "fixed_order": True,
                "outbound_cabin": "auto",
            },
            {
                "id": "stop-par",
                "label": "Paris",
                "airports": ["CDG"],
                "earliest_arrival": "2026-11-14",
                "latest_departure": "2026-11-19",
                "min_nights": 4,
                "max_nights": 4,
                "fixed_order": True,
                "outbound_cabin": "economy",
            },
        ],
        "provider_mode": "offline",
    }

    resp = client.post("/api/optimize", json=payload, headers={"X-Stream-Progress": "1"})
    assert resp.status_code == 200
    assert "application/x-ndjson" in resp.headers.get("content-type", "")

    events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    progress_events = [e for e in events if e["type"] == "progress"]
    result_events = [e for e in events if e["type"] == "result"]

    assert len(progress_events) >= 4
    assert any(e["phase"] == "query_start" and "→" in e["current_query"] for e in progress_events)
    assert any(e["phase"] == "query_done" and e.get("last_query") for e in progress_events)
    assert progress_events[-1]["phase"] == "complete"
    assert progress_events[-1]["progress_pct"] == 100
    assert progress_events[-1]["queries_completed"] == progress_events[-1]["queries_total"]

    assert len(result_events) == 1
    assert result_events[0]["data"]["api_version"] == 2
    assert result_events[0]["data"]["recommended"]["total_price_usd"] > 0
