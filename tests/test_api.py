"""FastAPI endpoint integration tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app

client = TestClient(app)


def test_health_and_airports_endpoints() -> None:
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


def test_simulation_is_testing_only_and_never_cached(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert body1["recommended"]["total_price_usd"] > 0
    assert len(body1["strategy_comparison"]) >= 4
    assert body1["cache_stats"]["total_cached_flights_in_db"] == 0
    assert body1["cache_stats"]["total_cached_quotes_in_db"] == 0
    assert any("simulated" in warning for warning in body1["warnings"])

    r2 = client.post("/api/optimize", json=payload)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["cache_stats"]["cache_misses"] == 0
    assert body2["cache_stats"]["cache_hits"] == 0
    assert body2["cache_stats"]["total_cached_flights_in_db"] == 0
    assert body2["cache_stats"]["total_cached_quotes_in_db"] == 0

    monkeypatch.delenv("FARESPLIT_TESTING")
    assert client.get("/api/provider-status").json()["testing_mode"] is False
    rejected = client.post("/api/optimize", json=payload)
    assert rejected.status_code == 403
    assert "disabled" in rejected.json()["detail"]

    monkeypatch.setattr(main.flight_provider, "_search_fast_flights", lambda *_args: [])
    monkeypatch.setattr(main.flight_provider, "_search_serpapi_google_flights", lambda *_args: [])
    payload["provider_mode"] = "auto"
    failed_live = client.post("/api/optimize", json=payload)
    assert failed_live.status_code == 400
    assert "No valid flight combinations" in failed_live.json()["detail"]


def test_optimize_rejects_degenerate_same_airport_stop() -> None:
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


def test_optimize_streams_progress_events_and_final_result(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert result_events[0]["data"]["recommended"]["total_price_usd"] > 0
