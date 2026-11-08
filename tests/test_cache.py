"""Tests for the SQLite flight-search cache."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest
from fast_flights.parser import parse as parse_fast_flights

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.queries import LegSearch, SearchIssue, SearchIssueKind, SearchResult, SearchStatus
from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption, ProviderMode
from backend.app.providers.base import CachedFlightProvider, FlightSearchProvider
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.providers.pricing_engine import RealisticPricingProvider


class MockLiveProvider(RealisticPricingProvider):
    def __init__(self) -> None:
        self.queries: list[LegSearch] = []

    def is_simulation(self) -> bool:
        return False

    def search(self, query: LegSearch) -> SearchResult:
        self.queries.append(query)
        return SearchResult(
            options=tuple(
                option.model_copy(update={"provider": "fast_flights"}) for option in super().search(query).options
            )
        )


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
    first_results = cached_provider.search(query).options
    assert len(first_results) > 0
    stats_after_first = cache.get_stats()
    assert stats_after_first.cache_misses == 1
    assert stats_after_first.cache_hits == 0
    assert stats_after_first.total_cached_flights_in_db == len(first_results)

    # The same run reuses its result; a new run reads the persistent cache.
    assert cached_provider.search(LegSearch.single(" sfo ", "lhr", dep_date, ConcreteCabinClass.BUSINESS)).options
    assert raw_provider.queries == [query]
    second_results = CachedFlightProvider(raw_provider, cache).search(query).options
    assert len(second_results) == len(first_results)
    assert all(opt.from_cache for opt in second_results)
    stats_after_second = cache.get_stats()
    assert stats_after_second.cache_hits == 1
    assert stats_after_second.cache_misses == 1

    # A cached SFO-LHR search does not cover the other airport pairs in a batch.
    batch_query = LegSearch(("SFO", "OAK"), ("LHR", "LGW"), dep_date, ConcreteCabinClass.BUSINESS)
    batch_results = cached_provider.search(batch_query).options
    assert any(opt.origin == "OAK" for opt in batch_results)
    assert any(opt.destination == "LGW" for opt in batch_results)
    assert all(not opt.from_cache for opt in batch_results)
    assert cache.get_stats().cache_misses == 2
    batch_again = CachedFlightProvider(raw_provider, cache).search(batch_query).options
    assert len(batch_again) == len(batch_results)
    assert all(opt.from_cache for opt in batch_again)
    assert cache.get_stats().cache_hits == 2

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
    assert cache.get_stats().total_cached_flights_in_db == len(options.options)


def test_persistent_search_cache_separates_provider_mode_and_layover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = FlightCache(tmp_path / "provider-scopes.db")
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    option = MockLiveProvider().search(query).options[0]
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
    assert CachedFlightProvider(fast, cache).search(query).options[0].provider == "fast_flights"
    assert CachedFlightProvider(fast, cache).search(query).options[0].from_cache
    assert CachedFlightProvider(serp, cache).search(query).options[0].provider == "serpapi"
    fast.max_layover_hours = 10.0
    assert not CachedFlightProvider(fast, cache).search(query).options[0].from_cache
    assert attempts == ["fast", "serp", "fast"]


@pytest.mark.parametrize("failure", ["error", "budget"])
def test_incomplete_nonempty_search_is_not_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    cache = FlightCache(tmp_path / "incomplete.db")
    provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS, max_api_calls=1 if failure == "budget" else 10)
    query = LegSearch(("SFO", "OAK"), ("LHR",), date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    option = MockLiveProvider().search(LegSearch.single("SFO", "LHR", query.departure_date, query.cabin)).options[0]
    attempts: list[str] = []

    def search(origin: str, *_args: object) -> list[FlightLegOption]:
        attempts.append(origin)
        provider.api_calls_this_run += 1
        if origin == "OAK":
            raise httpx.ConnectError("provider unavailable")
        return [option]

    monkeypatch.setattr(provider, "_search_fast_flights", search)
    run = CachedFlightProvider(provider, cache)
    result = run.search(query)
    assert result.options == (option,)
    assert result.status == SearchStatus.PARTIAL
    assert result.issues[0].kind == (
        SearchIssueKind.PROVIDER_ERROR if failure == "error" else SearchIssueKind.BUDGET_EXHAUSTED
    )
    assert run.search(query) == result
    assert run.search_issues == list(result.issues)
    assert cache.get_leg_options(query, provider_scope=provider.cache_scope()) is None

    provider.api_calls_this_run = 0
    CachedFlightProvider(provider, cache).search(query)
    assert attempts.count("SFO") == 2


def test_cache_refuses_partial_results_and_older_search_keys(tmp_path: Path) -> None:
    cache = FlightCache(tmp_path / "old-search.db")
    delegate = MockLiveProvider()
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    complete = delegate.search(query)
    issue = SearchIssue(SearchIssueKind.PROVIDER_ERROR, "The provider failed.")
    partial = SearchResult(options=complete.options, status=SearchStatus.PARTIAL, issues=(issue,))
    cache.store_leg_options(query, partial, provider_scope=delegate.cache_scope())
    assert cache.get_leg_options(query, provider_scope=delegate.cache_scope()) is None

    cache.store_leg_options(query, complete, provider_scope=delegate.cache_scope())
    with cache._connect() as conn:
        conn.execute("UPDATE leg_search_cache SET cache_key = replace(cache_key, 'search-v3:', 'search-v2:')")
    assert cache.get_leg_options(query, provider_scope=delegate.cache_scope()) is None


def test_shortlisted_airport_pairs_are_reported_and_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FlightCache(tmp_path / "shortlist.db")
    provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS)
    query = LegSearch(("SFO", "OAK"), ("LHR",), date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    options = list(MockLiveProvider().search(LegSearch.single("SFO", "LHR", query.departure_date, query.cabin)).options)
    assert len(options) >= 4
    attempts: list[str] = []

    def search(origin: str, *_args: object) -> list[FlightLegOption]:
        attempts.append(origin)
        return options

    monkeypatch.setattr(provider, "_search_fast_flights", search)
    result = CachedFlightProvider(provider, cache).search(query)
    assert result.status == SearchStatus.PARTIAL
    assert result.issues[0].kind == SearchIssueKind.TRUNCATED
    assert "1 of 2 airport pairs" in result.issues[0].message
    assert cache.get_leg_options(query, provider_scope=provider.cache_scope()) is None
    assert attempts == ["SFO"]


def test_auto_fallback_can_complete_a_failed_primary_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FlightCache(tmp_path / "recovered.db")
    provider = CompositeFlightProvider(mode=ProviderMode.AUTO)
    provider.serpapi_key = "test-key"
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    option = MockLiveProvider().search(query).options[0].model_copy(update={"provider": "serpapi"})
    attempts: list[str] = []

    def fail(*_args: object) -> list[FlightLegOption]:
        attempts.append("fast")
        raise httpx.ConnectError("private transport details")

    def recover(*_args: object) -> list[FlightLegOption]:
        attempts.append("serp")
        return [option]

    monkeypatch.setattr(provider, "_search_fast_flights", fail)
    monkeypatch.setattr(provider, "_search_serpapi_google_flights", recover)
    result = CachedFlightProvider(provider, cache).search(query)
    assert result.status == SearchStatus.COMPLETE
    assert result.options == (option,)
    assert result.issues[0].kind == SearchIssueKind.PROVIDER_ERROR
    assert "private transport details" not in result.issues[0].message
    assert CachedFlightProvider(provider, cache).search(query).options[0].from_cache
    assert attempts == ["fast", "serp"]


def test_fast_flights_retry_budget_is_reported_as_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS, max_api_calls=1, rate_limit_seconds=0)
    calls: list[object] = []

    def no_flights(query: object) -> list[object]:
        calls.append(query)
        return []

    monkeypatch.setattr("backend.app.providers.google_flights.get_flights", no_flights)
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    result = provider.search(query)
    assert result.status == SearchStatus.PARTIAL
    assert not result.options
    assert result.issues[0].kind == SearchIssueKind.BUDGET_EXHAUSTED
    assert len(calls) == provider.api_calls_this_run == 1


@pytest.mark.parametrize("mode", [ProviderMode.FAST_FLIGHTS, ProviderMode.AUTO])
@pytest.mark.parametrize("empty_first_attempt", [False, True])
def test_malformed_fast_flights_response_is_a_provider_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: ProviderMode,
    empty_first_attempt: bool,
    malformed_fast_flights_response: tuple[str, type[Exception]],
    fast_flights_html: Callable[[object], str],
) -> None:
    html, error_type = malformed_fast_flights_response
    with pytest.raises(error_type):
        parse_fast_flights(html)
    cache = FlightCache(tmp_path / "parser-error.db")
    provider = CompositeFlightProvider(cache=cache, mode=mode, rate_limit_seconds=0)
    provider.serpapi_key = "test-key"
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    recovered = MockLiveProvider().search(query).options[0].model_copy(update={"provider": "serpapi"})
    fast_calls: list[object] = []
    serp_calls: list[str] = []

    def malformed_response(query: object, **_kwargs: object) -> str:
        fast_calls.append(query)
        if empty_first_attempt and len(fast_calls) == 1:
            return fast_flights_html([None])
        return html

    def recover(*_args: object) -> list[FlightLegOption]:
        serp_calls.append("serpapi")
        return [recovered]

    monkeypatch.setattr("fast_flights.fetcher.fetch_flights_html", malformed_response)
    monkeypatch.setattr(provider, "_search_serpapi_google_flights", recover)
    result = CachedFlightProvider(provider, cache).search(query)
    assert len(fast_calls) == cache.get_stats().fast_flights_calls_this_run == (2 if empty_first_attempt else 1)
    assert result.issues[0].kind == SearchIssueKind.PROVIDER_ERROR
    assert f"unable to parse response ({error_type.__name__})" in result.issues[0].message
    if mode == ProviderMode.AUTO:
        assert result.status == SearchStatus.COMPLETE
        assert result.options == (recovered,)
        assert serp_calls == ["serpapi"]
        assert CachedFlightProvider(provider, cache).search(query).options[0].from_cache
    else:
        assert result.status == SearchStatus.FAILED
        assert not result.options
        assert not serp_calls
        assert cache.get_leg_options(query, provider_scope=provider.cache_scope()) is None


@pytest.mark.parametrize("empty_group", [None, [], [None], [[]]])
def test_fast_flights_accepts_missing_result_groups(
    empty_group: object, fast_flights_html: Callable[[object], str]
) -> None:
    parsed = parse_fast_flights(fast_flights_html(empty_group))
    assert parsed == []
    assert parsed.metadata.airlines == []


def test_fast_flights_skips_unpriced_itineraries(fast_flights_html: Callable[[object], str]) -> None:
    segment: list[object] = [None] * 22
    segment[3:7] = ["AAA", "Origin", "Destination", "BBB"]
    segment[8], segment[10] = [9], [11]
    segment[11], segment[17] = 120, "Test aircraft"
    segment[20] = segment[21] = [2026, 10, 1]
    flight: list[object] = [None] * 23
    flight[0:3] = ["nonstop", ["Test Airline"], [segment]]
    flight[22] = [None] * 7 + [100000, 120000]
    parsed = parse_fast_flights(fast_flights_html([[[flight, []]]]))

    assert len(parsed) == 1
    assert parsed[0].price is None
    assert (
        CompositeFlightProvider.parse_fast_flights_results(
            parsed,
            "AAA",
            "BBB",
            date(2026, 10, 1),
            ConcreteCabinClass.ECONOMY,
        )
        == []
    )


@pytest.mark.parametrize("error_type", [IndexError, TypeError, AttributeError, KeyError, ValueError])
def test_fast_flights_adapter_errors_still_propagate(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS, rate_limit_seconds=0)

    def fetched(_query: object) -> list[object]:
        return [object()]

    def broken(**_kwargs: object) -> list[FlightLegOption]:
        raise error_type("adapter implementation error")

    monkeypatch.setattr("backend.app.providers.google_flights.get_flights", fetched)
    monkeypatch.setattr(provider, "parse_fast_flights_results", broken)
    with pytest.raises(error_type, match="adapter implementation error"):
        provider.search(LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS))


@pytest.mark.parametrize("status_code", [200, 403])
def test_serpapi_error_response_is_not_empty_availability(monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
    provider = CompositeFlightProvider(mode=ProviderMode.SERPAPI, rate_limit_seconds=0)
    provider.serpapi_key = "test-key"
    client = httpx.Client
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, json={"error": "private provider detail"})
    )
    monkeypatch.setattr(
        "backend.app.providers.google_flights.httpx.Client", lambda **_kwargs: client(transport=transport)
    )

    result = provider.search(LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS))
    assert result.status == SearchStatus.FAILED
    assert result.issues[0].kind == SearchIssueKind.PROVIDER_ERROR
    assert "private provider detail" not in result.issues[0].message
    assert "test-key" not in result.issues[0].message


def test_search_result_rejects_inconsistent_outcomes() -> None:
    with pytest.raises(ValueError, match="must report an issue"):
        SearchResult(status=SearchStatus.PARTIAL)
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    issue = SearchIssue(SearchIssueKind.PROVIDER_ERROR, "Provider unavailable.")
    with pytest.raises(ValueError, match="cannot contain options"):
        SearchResult(options=MockLiveProvider().search(query).options, status=SearchStatus.FAILED, issues=(issue,))


def test_missing_serpapi_credentials_are_reported() -> None:
    provider = CompositeFlightProvider(mode=ProviderMode.SERPAPI)
    provider.serpapi_key = ""
    result = provider.search(LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS))
    assert result.status == SearchStatus.FAILED
    assert result.issues[0].kind == SearchIssueKind.MISSING_CREDENTIALS
    assert provider.api_calls_this_run == 0


def test_programming_errors_are_not_reported_as_provider_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS)

    def broken(*_args: object) -> list[FlightLegOption]:
        raise RuntimeError("implementation error")

    monkeypatch.setattr(provider, "_search_fast_flights", broken)
    with pytest.raises(RuntimeError, match="implementation error"):
        provider.search(LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS))


@pytest.mark.parametrize("force_refresh", [False, True])
@pytest.mark.parametrize("status", [SearchStatus.COMPLETE, SearchStatus.FAILED])
def test_empty_search_is_reused_only_within_the_run(tmp_path: Path, force_refresh: bool, status: SearchStatus) -> None:
    outcome = SearchResult(
        status=status,
        issues=(SearchIssue(SearchIssueKind.PROVIDER_ERROR, "Provider unavailable."),)
        if status == SearchStatus.FAILED
        else (),
    )

    class EmptyProvider(FlightSearchProvider):
        def __init__(self) -> None:
            self.queries: list[LegSearch] = []

        def search(self, query: LegSearch) -> SearchResult:
            self.queries.append(query)
            return outcome

    cache = FlightCache(tmp_path / "empty.db")
    delegate = EmptyProvider()
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    run = CachedFlightProvider(delegate, cache, force_refresh=force_refresh)
    assert run.search(query) == outcome
    assert run.search(query) == outcome
    assert delegate.queries == [query]
    assert cache.get_stats().cache_misses == 1
    assert CachedFlightProvider(delegate, cache, force_refresh=force_refresh).search(query) == outcome
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
            raise httpx.ConnectError("Live provider unavailable")
        return []

    monkeypatch.setattr(provider, "_search_fast_flights", unavailable)
    monkeypatch.setattr(provider, "_search_serpapi_google_flights", unavailable)
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    for search in (query, LegSearch(("SFO", "OAK"), ("LHR",), query.departure_date, query.cabin)):
        result = provider.search(search)
        assert not result.options
        assert result.status == (SearchStatus.COMPLETE if failure == "empty" else SearchStatus.FAILED)
        if failure != "empty":
            assert result.issues


def test_composite_does_not_repeat_failed_primary_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS)
    attempts: list[tuple[str, str]] = []

    def empty(origin: str, destination: str, *_args: object) -> list[FlightLegOption]:
        attempts.append((origin, destination))
        return []

    monkeypatch.setattr(provider, "_search_fast_flights", empty)
    query = LegSearch(("SFO", "OAK", "SJC"), ("LHR", "LGW"), date(2026, 11, 10), ConcreteCabinClass.ECONOMY)
    assert provider.search(query) == SearchResult()
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
    assert provider.search(LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.ECONOMY)) == (
        SearchResult()
    )
    assert attempts == [("SFO", "LHR")]


def test_simulation_requires_explicit_testing_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FARESPLIT_TESTING", raising=False)
    provider = CompositeFlightProvider(mode=ProviderMode.OFFLINE)
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    with pytest.raises(ValueError, match="FARESPLIT_TESTING=1"):
        provider.search(query)
    monkeypatch.setenv("FARESPLIT_TESTING", "1")
    results = provider.search(query).options
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
        single = provider.search(query).options
        batch = provider.search(LegSearch(("SFO",), ("LHR",), departure, ConcreteCabinClass.BUSINESS)).options
        assert single
        assert batch
        assert all(option.provider == "pricing_engine" and not option.from_cache for option in single + batch)
    after = cache.get_stats()
    assert after.total_cached_flights_in_db == before.total_cached_flights_in_db
    assert after.cache_hits == after.cache_misses == 0


def test_cache_rejects_simulated_and_mixed_search_results(tmp_path: Path) -> None:
    cache = FlightCache(tmp_path / "rejected.db")
    departure = date(2026, 11, 10)
    query = LegSearch.single("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    fake = RealisticPricingProvider().search(query)
    live_provider = MockLiveProvider()
    live = live_provider.search(query)
    for result in (fake, SearchResult(options=fake.options + live.options)):
        cache.store_leg_options(query, result, provider_scope=live_provider.cache_scope())
    assert cache.get_stats().total_cached_flights_in_db == 0
    assert cache.get_leg_options(query, provider_scope=live_provider.cache_scope()) is None


def test_legacy_simulated_flight_cache_is_removed_without_deleting_live_data(tmp_path: Path) -> None:
    cache = FlightCache(tmp_path / "legacy.db")
    departure = date(2026, 11, 10)
    query = LegSearch.single("SFO", "LHR", departure, ConcreteCabinClass.BUSINESS)
    live_provider = MockLiveProvider()
    result = live_provider.search(query)
    live = result.options
    cache.store_leg_options(query, result, provider_scope=live_provider.cache_scope())
    cache.record_provider_call("serpapi")
    with cache._connect() as conn:
        conn.execute(
            "UPDATE leg_search_cache SET payload_json = ?",
            (json.dumps([live[0].model_copy(update={"provider": "pricing_engine"}).model_dump(mode="json")]),),
        )
        conn.execute(
            "UPDATE granular_flights SET payload_json = ? WHERE leg_id = ?",
            (live[0].model_copy(update={"provider": "pricing_engine"}).model_dump_json(), live[0].leg_id),
        )
    cache = FlightCache(cache.db_path)
    results = cache.get_leg_options(query, provider_scope=live_provider.cache_scope())
    assert results is None
    with cache._connect() as conn:
        rows = conn.execute("SELECT payload_json FROM granular_flights").fetchall()
    assert len(rows) == len(live) - 1
    assert all(json.loads(row["payload_json"])["provider"] == "fast_flights" for row in rows)
    assert cache.get_stats().total_serpapi_calls_logged == 1
