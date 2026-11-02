"""Tests for airport registry, nearby airport suggestions, and per-leg cabin class resolution."""

from __future__ import annotations

from backend.app.data.airports import (
    candidate_intermediate_hubs,
    estimate_nonstop_hours,
    haversine_km,
    same_metro_area,
    suggest_airports,
)
from backend.app.models.schemas import (
    CabinClass,
    CabinPolicy,
    ConcreteCabinClass,
)
from backend.app.solver.cabin import highest_cabin, resolve_leg_cabin


def test_paris_nearby_airports_exclude_brussels() -> None:
    suggestions = suggest_airports("Paris")
    assert suggestions
    cdg = next(item for item in suggestions if item["code"] == "CDG")
    nearby_codes = [nb["code"] for nb in cdg["nearby"]]
    assert "ORY" in nearby_codes
    assert "BVA" in nearby_codes
    assert "BRU" not in nearby_codes


def test_same_metro_area_and_distance() -> None:
    assert same_metro_area("LHR", "LGW") is True
    assert same_metro_area("HND", "NRT") is True
    assert same_metro_area("CDG", "BRU") is False
    assert haversine_km("SFO", "LHR") > 8000
    assert estimate_nonstop_hours("SFO", "LHR") > 9.0
    assert estimate_nonstop_hours("LHR", "CDG") < 2.0


def test_candidate_intermediate_hubs() -> None:
    # Long-haul SFO -> BKK should find sensible Pacific/Asian gateway hubs
    hubs = candidate_intermediate_hubs("SFO", "BKK", max_hubs=3)
    assert len(hubs) >= 1
    assert any(h in ("TPE", "HND", "NRT", "ICN", "HKG") for h in hubs)
    # Short-haul LHR -> CDG should not suggest hub splitting
    assert candidate_intermediate_hubs("LHR", "CDG") == []


def test_resolve_leg_cabin_auto_and_explicit() -> None:
    policy = CabinPolicy(
        default_cabin=ConcreteCabinClass.ECONOMY,
        long_haul_cabin=ConcreteCabinClass.BUSINESS,
        long_haul_threshold_hours=6.5,
    )
    # Long-haul leg (SFO -> LHR ~10.9h) under AUTO resolves to BUSINESS
    assert resolve_leg_cabin("SFO", "LHR", CabinClass.AUTO, policy) == ConcreteCabinClass.BUSINESS
    # Short-haul leg (LHR -> CDG ~1.1h) under AUTO resolves to ECONOMY
    assert resolve_leg_cabin("LHR", "CDG", CabinClass.AUTO, policy) == ConcreteCabinClass.ECONOMY
    # Explicit override is always respected regardless of flight length
    assert resolve_leg_cabin("SFO", "LHR", CabinClass.ECONOMY, policy) == ConcreteCabinClass.ECONOMY
    assert resolve_leg_cabin("LHR", "CDG", CabinClass.FIRST, policy) == ConcreteCabinClass.FIRST


def test_highest_cabin_ranking() -> None:
    assert highest_cabin([ConcreteCabinClass.ECONOMY, ConcreteCabinClass.BUSINESS]) == ConcreteCabinClass.BUSINESS
    assert highest_cabin([ConcreteCabinClass.PREMIUM_ECONOMY, ConcreteCabinClass.FIRST]) == ConcreteCabinClass.FIRST
