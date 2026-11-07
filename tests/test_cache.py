"""Tests for the two-tier SQLite flight and ticket quote cache."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pytest

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption, ProviderMode, TicketType
from backend.app.providers.base import CachedFlightProvider
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.providers.pricing_engine import RealisticPricingProvider


class MockLiveProvider(RealisticPricingProvider):
    def is_simulation(self) -> bool:
        return False

    def search_leg(
        self, origin: str, destination: str, departure_date: date, cabin: ConcreteCabinClass
    ) -> list[FlightLegOption]:
        return [
            option.model_copy(update={"provider": "fast_flights"})
            for option in super().search_leg(origin, destination, departure_date, cabin)
        ]


def test_sqlite_cache_hit_miss_and_granular_persistence(tmp_path: Path) -> None:
    db_file = tmp_path / "test_flights.db"
    cache = FlightCache(db_path=db_file)
    raw_provider = MockLiveProvider()
    cached_provider = CachedFlightProvider(delegate=raw_provider, cache=cache)

    dep_date = date(2026, 11, 10)
    # 1st lookup should miss cache and populate both leg_search_cache and granular_flights
    first_results = cached_provider.search_leg("SFO", "LHR", dep_date, ConcreteCabinClass.BUSINESS)
    assert len(first_results) > 0
    stats_after_first = cache.get_stats()
    assert stats_after_first.cache_misses == 1
    assert stats_after_first.cache_hits == 0
    assert stats_after_first.total_cached_flights_in_db == len(first_results)

    # 2nd identical lookup should hit SQLite cache and mark from_cache=True
    second_results = cached_provider.search_leg("SFO", "LHR", dep_date, ConcreteCabinClass.BUSINESS)
    assert len(second_results) == len(first_results)
    assert all(opt.from_cache for opt in second_results)
    stats_after_second = cache.get_stats()
    assert stats_after_second.cache_hits == 1
    assert stats_after_second.cache_misses == 1

    # Multi-slice ticket quote caching
    fare_1 = cached_provider.quote_multi_slice_ticket(first_results[:2], TicketType.OPEN_JAW)
    fare_2 = cached_provider.quote_multi_slice_ticket(first_results[:2], TicketType.OPEN_JAW)
    assert fare_1 == fare_2
    assert cache.get_stats().cache_hits == 2

    # A cached SFO-LHR search does not cover the other airport pairs in a batch.
    batch_results = cached_provider.search_leg_batch(
        ("SFO", "OAK"), ("LHR", "LGW"), dep_date, ConcreteCabinClass.BUSINESS
    )
    assert any(opt.origin == "OAK" for opt in batch_results)
    assert any(opt.destination == "LGW" for opt in batch_results)
    assert all(not opt.from_cache for opt in batch_results)
    assert cache.get_stats().cache_misses == 3  # search, quote, batch
    batch_again = cached_provider.search_leg_batch(
        ("SFO", "OAK"), ("LHR", "LGW"), dep_date, ConcreteCabinClass.BUSINESS
    )
    assert len(batch_again) == len(batch_results)
    assert all(opt.from_cache for opt in batch_again)
    assert cache.get_stats().cache_hits == 3

    # Force-refresh on search_leg_batch increments session_misses
    refresh_provider = CachedFlightProvider(delegate=raw_provider, cache=cache, force_refresh=True)
    misses_before = cache.get_stats().cache_misses
    refresh_provider.search_leg_batch(("SFO",), ("LHR",), dep_date, ConcreteCabinClass.BUSINESS)
    assert cache.get_stats().cache_misses == misses_before + 1

    # Provider usage logging persists across clear_all()
    cache.record_provider_call("serpapi")
    cache.record_provider_call("serpapi")
    assert cache.get_stats().serpapi_calls_this_run == 2
    assert cache.get_stats().total_serpapi_calls_logged == 2

    # Clearing cache empties flight tables while preserving lifetime SerpApi quota count
    cache.clear_all()
    cleared_stats = cache.get_stats()
    assert cleared_stats.total_cached_flights_in_db == 0
    assert cleared_stats.total_cached_quotes_in_db == 0
    assert cleared_stats.total_serpapi_calls_logged == 2


def test_expired_search_is_not_recreated_from_granular_flights(tmp_path: Path) -> None:
    cache = FlightCache(tmp_path / "expired.db", ttl_seconds=60)
    departure = date(2026, 11, 10)
    options = MockLiveProvider().search_leg("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    cache.store_leg_options("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS, options)
    with cache._connect() as conn:
        conn.execute("UPDATE leg_search_cache SET updated_at = ?", (time.time() - 61,))

    assert cache.get_leg_options("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS) is None
    assert cache.get_stats().cache_misses == 1
    assert cache.get_stats().total_cached_flights_in_db == len(options)


@pytest.mark.parametrize("mode", [ProviderMode.AUTO, ProviderMode.FAST_FLIGHTS, ProviderMode.SERPAPI])
@pytest.mark.parametrize("failure", ["empty", "error", "budget"])
def test_live_search_never_falls_back_to_simulation(
    monkeypatch: pytest.MonkeyPatch, mode: ProviderMode, failure: str
) -> None:
    provider = CompositeFlightProvider(mode=mode, max_api_calls=0 if failure == "budget" else 25)
    provider.serpapi_key = "test-key"

    def unavailable(*_args: object) -> list[FlightLegOption]:
        if failure == "error":
            raise RuntimeError("Live provider unavailable")
        return []

    monkeypatch.setattr(provider, "_search_fast_flights", unavailable)
    monkeypatch.setattr(provider, "_search_serpapi_google_flights", unavailable)
    assert provider.search_leg("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS) == []
    assert provider.search_leg_batch(("SFO",), ("LHR",), date(2026, 11, 10), ConcreteCabinClass.BUSINESS) == []


def test_simulation_requires_explicit_testing_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FARESPLIT_TESTING", raising=False)
    provider = CompositeFlightProvider(mode=ProviderMode.OFFLINE)
    with pytest.raises(ValueError, match="FARESPLIT_TESTING=1"):
        provider.search_leg("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    monkeypatch.setenv("FARESPLIT_TESTING", "1")
    results = provider.search_leg("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    assert results
    assert all(option.provider == "pricing_engine" for option in results)


def test_simulation_bypasses_real_cache_and_never_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FARESPLIT_TESTING", "1")
    cache = FlightCache(tmp_path / "simulation.db")
    departure = date(2026, 11, 10)
    live = MockLiveProvider().search_leg("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    cache.store_leg_options("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS, live)
    before = cache.get_stats()
    for delegate in (RealisticPricingProvider(), CompositeFlightProvider(mode=ProviderMode.OFFLINE)):
        provider = CachedFlightProvider(delegate, cache)
        single = provider.search_leg("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
        batch = provider.search_leg_batch(("SFO",), ("LHR",), departure, ConcreteCabinClass.BUSINESS)
        assert single
        assert batch
        assert all(option.provider == "pricing_engine" and not option.from_cache for option in single + batch)
        assert provider.quote_multi_slice_ticket(single[:2], TicketType.OPEN_JAW) > 0
    after = cache.get_stats()
    assert after.total_cached_flights_in_db == before.total_cached_flights_in_db
    assert after.total_cached_quotes_in_db == before.total_cached_quotes_in_db
    assert after.cache_hits == after.cache_misses == 0


def test_cache_rejects_simulated_and_mixed_writes(tmp_path: Path) -> None:
    cache = FlightCache(tmp_path / "rejected.db")
    departure = date(2026, 11, 10)
    fake = RealisticPricingProvider().search_leg("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    live = MockLiveProvider().search_leg("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    for options in (fake, fake + live):
        cache.store_leg_options("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS, options)
    cache.store_ticket_quote("simulated", "open_jaw", {"providers": ["pricing_engine"], "base_fare_usd": 100})
    assert cache.get_stats().total_cached_flights_in_db == 0
    assert cache.get_stats().total_cached_quotes_in_db == 0
    assert cache.get_leg_options("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS) is None


def test_legacy_simulated_cache_is_removed_without_deleting_live_data(tmp_path: Path) -> None:
    cache = FlightCache(tmp_path / "legacy.db")
    departure = date(2026, 11, 10)
    live = MockLiveProvider().search_leg("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    cache.store_leg_options("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS, live)
    cache.record_provider_call("serpapi")
    cache.store_ticket_quote("live-quote", "open_jaw", {"providers": ["fast_flights"], "base_fare_usd": 200})
    with cache._connect() as conn:
        conn.execute(
            "UPDATE leg_search_cache SET payload_json = ?",
            (json.dumps([live[0].model_copy(update={"provider": "pricing_engine"}).model_dump(mode="json")]),),
        )
        conn.execute(
            "UPDATE granular_flights SET payload_json = ? WHERE leg_id = ?",
            (live[0].model_copy(update={"provider": "pricing_engine"}).model_dump_json(), live[0].leg_id),
        )
        conn.execute(
            "INSERT INTO ticket_quote_cache VALUES (?, ?, ?, ?)",
            ("legacy-quote", "open_jaw", json.dumps({"base_fare_usd": 100}), time.time()),
        )
    cache = FlightCache(cache.db_path)
    results = cache.get_leg_options("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    assert results is None
    with cache._connect() as conn:
        rows = conn.execute("SELECT payload_json FROM granular_flights").fetchall()
    assert len(rows) == len(live) - 1
    assert all(json.loads(row["payload_json"])["provider"] == "fast_flights" for row in rows)
    assert cache.get_ticket_quote("legacy-quote") is None
    assert cache.get_ticket_quote("live-quote") == {"providers": ["fast_flights"], "base_fare_usd": 200}
    assert cache.get_stats().total_serpapi_calls_logged == 1
