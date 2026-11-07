"""Tests for the two-tier SQLite flight and ticket quote cache."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pytest

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.queries import LegSearch
from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption, ProviderMode, TicketType
from backend.app.providers.base import CachedFlightProvider, FlightSearchProvider
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.providers.pricing_engine import RealisticPricingProvider


class MockLiveProvider(RealisticPricingProvider):
    def __init__(self) -> None:
        self.queries: list[LegSearch] = []

    def is_simulation(self) -> bool:
        return False

    def search(self, query: LegSearch) -> list[FlightLegOption]:
        self.queries.append(query)
        return [option.model_copy(update={"provider": "fast_flights"}) for option in super().search(query)]


def test_leg_search_normalizes_codes_without_changing_airport_priority() -> None:
    departure = date(2026, 11, 10)
    query = LegSearch((" sfo ", "SFO", "oak"), (" lhr", "LGW", "lhr "), departure, ConcreteCabinClass.BUSINESS)
    assert query.origins == ("SFO", "OAK")
    assert query.destinations == ("LHR", "LGW")
    assert query == LegSearch(("SFO", "OAK"), ("LHR", "LGW"), departure, ConcreteCabinClass.BUSINESS)
    assert FlightCache.make_leg_key(query, "test") != FlightCache.make_leg_key(
        LegSearch(("OAK", "SFO"), ("LHR", "LGW"), departure, ConcreteCabinClass.BUSINESS), "test"
    )
    with pytest.raises(ValueError, match="origin and destination"):
        LegSearch(("",), ("LHR",), departure, ConcreteCabinClass.BUSINESS)


def test_sqlite_cache_hit_miss_and_granular_persistence(tmp_path: Path) -> None:
    db_file = tmp_path / "test_flights.db"
    cache = FlightCache(db_path=db_file)
    raw_provider = MockLiveProvider()
    cached_provider = CachedFlightProvider(delegate=raw_provider, cache=cache)

    dep_date = date(2026, 11, 10)
    query = LegSearch.single("SFO", "LHR", dep_date, ConcreteCabinClass.BUSINESS)
    # 1st lookup should miss cache and populate both leg_search_cache and granular_flights
    first_results = cached_provider.search(query)
    assert len(first_results) > 0
    stats_after_first = cache.get_stats()
    assert stats_after_first.cache_misses == 1
    assert stats_after_first.cache_hits == 0
    assert stats_after_first.total_cached_flights_in_db == len(first_results)

    # The same run reuses its result; a new run reads the persistent cache.
    assert cached_provider.search(LegSearch.single(" sfo ", "lhr", dep_date, ConcreteCabinClass.BUSINESS))
    assert raw_provider.queries == [query]
    second_results = CachedFlightProvider(raw_provider, cache).search(query)
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
    batch_query = LegSearch(("SFO", "OAK"), ("LHR", "LGW"), dep_date, ConcreteCabinClass.BUSINESS)
    batch_results = cached_provider.search(batch_query)
    assert any(opt.origin == "OAK" for opt in batch_results)
    assert any(opt.destination == "LGW" for opt in batch_results)
    assert all(not opt.from_cache for opt in batch_results)
    assert cache.get_stats().cache_misses == 3  # search, quote, batch
    batch_again = CachedFlightProvider(raw_provider, cache).search(batch_query)
    assert len(batch_again) == len(batch_results)
    assert all(opt.from_cache for opt in batch_again)
    assert cache.get_stats().cache_hits == 3

    # Force refresh bypasses SQLite once per query, not once per strategy.
    refresh_provider = CachedFlightProvider(delegate=raw_provider, cache=cache, force_refresh=True)
    misses_before = cache.get_stats().cache_misses
    calls_before = len(raw_provider.queries)
    refresh_provider.search(query)
    refresh_provider.search(query)
    assert cache.get_stats().cache_misses == misses_before + 1
    assert len(raw_provider.queries) == calls_before + 1

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
    query = LegSearch.single("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    delegate = MockLiveProvider()
    options = delegate.search(query)
    cache.store_leg_options(query, options, provider_scope=delegate.cache_scope())
    with cache._connect() as conn:
        conn.execute("UPDATE leg_search_cache SET updated_at = ?", (time.time() - 61,))

    assert cache.get_leg_options(query, provider_scope=delegate.cache_scope()) is None
    assert cache.get_stats().cache_misses == 1
    assert cache.get_stats().total_cached_flights_in_db == len(options)


def test_persistent_search_cache_separates_provider_mode_and_layover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = FlightCache(tmp_path / "provider-scopes.db")
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    option = MockLiveProvider().search(query)[0]
    fast = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS, rate_limit_seconds=0)
    serp = CompositeFlightProvider(mode=ProviderMode.SERPAPI, rate_limit_seconds=0)
    serp.serpapi_key = "test-key"
    attempts: list[str] = []

    def fast_search(*_args: object) -> list[FlightLegOption]:
        attempts.append("fast")
        return [option]

    def serp_search(*_args: object) -> list[FlightLegOption]:
        attempts.append("serp")
        return [option.model_copy(update={"provider": "serpapi", "one_way_base_fare_usd": 123.0})]

    monkeypatch.setattr(fast, "_search_fast_flights", fast_search)
    monkeypatch.setattr(serp, "_search_serpapi_google_flights", serp_search)
    assert CachedFlightProvider(fast, cache).search(query)[0].provider == "fast_flights"
    assert CachedFlightProvider(fast, cache).search(query)[0].from_cache
    assert CachedFlightProvider(serp, cache).search(query)[0].provider == "serpapi"
    fast.max_layover_hours = 10.0
    assert not CachedFlightProvider(fast, cache).search(query)[0].from_cache
    assert attempts == ["fast", "serp", "fast"]


@pytest.mark.parametrize("force_refresh", [False, True])
def test_empty_search_is_reused_only_within_the_run(tmp_path: Path, force_refresh: bool) -> None:
    class EmptyProvider(FlightSearchProvider):
        def __init__(self) -> None:
            self.queries: list[LegSearch] = []

        def search(self, query: LegSearch) -> list[FlightLegOption]:
            self.queries.append(query)
            return []

    cache = FlightCache(tmp_path / "empty.db")
    delegate = EmptyProvider()
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    run = CachedFlightProvider(delegate, cache, force_refresh=force_refresh)
    assert run.search(query) == []
    assert run.search(query) == []
    assert delegate.queries == [query]
    assert cache.get_stats().cache_misses == 1
    assert CachedFlightProvider(delegate, cache, force_refresh=force_refresh).search(query) == []
    assert delegate.queries == [query, query]
    assert cache.get_stats().total_cached_flights_in_db == 0


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
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    assert provider.search(query) == []
    assert provider.search(LegSearch(("SFO", "OAK"), ("LHR",), query.departure_date, query.cabin)) == []


def test_composite_does_not_repeat_failed_primary_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS)
    attempts: list[tuple[str, str]] = []

    def empty(origin: str, destination: str, *_args: object) -> list[FlightLegOption]:
        attempts.append((origin, destination))
        return []

    monkeypatch.setattr(provider, "_search_fast_flights", empty)
    query = LegSearch(("SFO", "OAK", "SJC"), ("LHR", "LGW"), date(2026, 11, 10), ConcreteCabinClass.ECONOMY)
    assert provider.search(query) == []
    assert attempts == [
        ("SFO", "LHR"),
        ("SFO", "LGW"),
        ("OAK", "LHR"),
        ("OAK", "LGW"),
        ("SJC", "LHR"),
        ("SJC", "LGW"),
    ]


def test_serpapi_single_airport_search_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CompositeFlightProvider(mode=ProviderMode.SERPAPI)
    provider.serpapi_key = "test-key"
    attempts: list[tuple[str, str]] = []

    def empty(origin: str, destination: str, *_args: object) -> list[FlightLegOption]:
        attempts.append((origin, destination))
        return []

    monkeypatch.setattr(provider, "_search_serpapi_google_flights", empty)
    assert provider.search(LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.ECONOMY)) == []
    assert attempts == [("SFO", "LHR")]


def test_simulation_requires_explicit_testing_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FARESPLIT_TESTING", raising=False)
    provider = CompositeFlightProvider(mode=ProviderMode.OFFLINE)
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    with pytest.raises(ValueError, match="FARESPLIT_TESTING=1"):
        provider.search(query)
    monkeypatch.setenv("FARESPLIT_TESTING", "1")
    results = provider.search(query)
    assert results
    assert all(option.provider == "pricing_engine" for option in results)


def test_simulation_bypasses_real_cache_and_never_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FARESPLIT_TESTING", "1")
    cache = FlightCache(tmp_path / "simulation.db")
    departure = date(2026, 11, 10)
    query = LegSearch.single("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    live_provider = MockLiveProvider()
    live = live_provider.search(query)
    cache.store_leg_options(query, live, provider_scope=live_provider.cache_scope())
    before = cache.get_stats()
    for delegate in (RealisticPricingProvider(), CompositeFlightProvider(mode=ProviderMode.OFFLINE)):
        provider = CachedFlightProvider(delegate, cache)
        single = provider.search(query)
        batch = provider.search(LegSearch(("SFO",), ("LHR",), departure, ConcreteCabinClass.BUSINESS))
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
    query = LegSearch.single("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    fake = RealisticPricingProvider().search(query)
    live_provider = MockLiveProvider()
    live = live_provider.search(query)
    for options in (fake, fake + live):
        cache.store_leg_options(query, options, provider_scope=live_provider.cache_scope())
    cache.store_ticket_quote("simulated", "open_jaw", {"providers": ["pricing_engine"], "base_fare_usd": 100})
    assert cache.get_stats().total_cached_flights_in_db == 0
    assert cache.get_stats().total_cached_quotes_in_db == 0
    assert cache.get_leg_options(query, provider_scope=live_provider.cache_scope()) is None


def test_legacy_simulated_cache_is_removed_without_deleting_live_data(tmp_path: Path) -> None:
    cache = FlightCache(tmp_path / "legacy.db")
    departure = date(2026, 11, 10)
    query = LegSearch.single("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    live_provider = MockLiveProvider()
    live = live_provider.search(query)
    cache.store_leg_options(query, live, provider_scope=live_provider.cache_scope())
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
    results = cache.get_leg_options(query, provider_scope=live_provider.cache_scope())
    assert results is None
    with cache._connect() as conn:
        rows = conn.execute("SELECT payload_json FROM granular_flights").fetchall()
    assert len(rows) == len(live) - 1
    assert all(json.loads(row["payload_json"])["provider"] == "fast_flights" for row in rows)
    assert cache.get_ticket_quote("legacy-quote") is None
    assert cache.get_ticket_quote("live-quote") == {"providers": ["fast_flights"], "base_fare_usd": 200}
    assert cache.get_stats().total_serpapi_calls_logged == 1
