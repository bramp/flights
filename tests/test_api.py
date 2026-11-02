"""FastAPI endpoint integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

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


def test_optimize_and_cache_endpoints() -> None:
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
        "force_refresh": False,
    }

    r1 = client.post("/api/optimize", json=payload)
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["recommended"]["total_price_usd"] > 0
    assert len(body1["strategy_comparison"]) >= 4
    assert body1["cache_stats"]["total_cached_flights_in_db"] > 0

    # Second run with identical parameters should hit SQLite cache with 0 misses
    r2 = client.post("/api/optimize", json=payload)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["cache_stats"]["cache_misses"] == 0
    assert body2["cache_stats"]["cache_hits"] > 0


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
