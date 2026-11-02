"""Tests for the two-tier SQLite flight and ticket quote cache."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.schemas import ConcreteCabinClass, TicketType
from backend.app.providers.base import CachedFlightProvider
from backend.app.providers.pricing_engine import RealisticPricingProvider


def test_sqlite_cache_hit_miss_and_granular_persistence(tmp_path: Path) -> None:
    db_file = tmp_path / "test_flights.db"
    cache = FlightCache(db_path=db_file)
    raw_provider = RealisticPricingProvider()
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

    # Clearing cache empties tables
    cache.clear_all()
    cleared_stats = cache.get_stats()
    assert cleared_stats.total_cached_flights_in_db == 0
    assert cleared_stats.total_cached_quotes_in_db == 0
