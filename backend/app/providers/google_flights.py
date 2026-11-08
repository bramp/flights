"""Search live flight providers, parse responses, and build search links.

The composite provider supports fast-flights, SerpApi, and a test-only
simulator. Wrap live searches in ``CachedFlightProvider`` so they use the
flight cache.
"""

from __future__ import annotations

import itertools
import json
import logging
import math
import os
import time
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from fast_flights import FlightQuery, FlightsNotFound, Passengers, create_query, fetch_flights_html
from fast_flights.parser import parse as parse_fast_flights_html
from fast_flights.types import SeatType, TripType
from primp import PrimpError

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.data.airports import (
    record_observed_duration,
    register_discovered_airport,
)
from backend.app.models.queries import LegSearch, SearchIssue, SearchIssueKind, SearchResult, SearchStatus
from backend.app.models.schemas import (
    BaggageConfig,
    ConcreteCabinClass,
    FlightLegOption,
    FlightSegment,
    ProviderMode,
    StopsPolicy,
    TicketType,
)
from backend.app.providers.base import FlightSearchProvider
from backend.app.providers.pricing_engine import CARRIERS, RealisticPricingProvider
from backend.app.providers.provider_recordings import record_provider_response

load_dotenv()

_LOGGER = logging.getLogger(__name__)
_SEAT_TYPE_MAP: dict[ConcreteCabinClass, SeatType] = {
    ConcreteCabinClass.ECONOMY: "economy",
    ConcreteCabinClass.PREMIUM_ECONOMY: "premium-economy",
    ConcreteCabinClass.BUSINESS: "business",
    ConcreteCabinClass.FIRST: "first",
}
_CABIN_ORDER: dict[ConcreteCabinClass, int] = {
    ConcreteCabinClass.ECONOMY: 1,
    ConcreteCabinClass.PREMIUM_ECONOMY: 2,
    ConcreteCabinClass.BUSINESS: 3,
    ConcreteCabinClass.FIRST: 4,
}


def _extract_simple_datetime(dt_obj: Any) -> datetime | None:
    """Extract a fast-flights local wall time from date and time tuples.

    The returned datetime is tagged with UTC without converting the local
    time; it does not represent a verified UTC instant. A missing time
    defaults to midnight. Missing or invalid calendar values return ``None``.
    Time components that cannot be converted to integers can raise an error.

    Examples:
        >>> from types import SimpleNamespace
        >>> from backend.app.providers.google_flights import _extract_simple_datetime
        >>> raw = SimpleNamespace(date=(2026, 11, 10), time=(9, 30))
        >>> _extract_simple_datetime(raw).isoformat()
        '2026-11-10T09:30:00+00:00'
    """
    if dt_obj is None:
        return None
    d_tuple = getattr(dt_obj, "date", None)
    t_tuple = getattr(dt_obj, "time", None)
    if isinstance(d_tuple, (tuple, list)) and len(d_tuple) == 3 and all(isinstance(x, int) for x in d_tuple):
        hh = 0
        mm = 0
        if isinstance(t_tuple, (tuple, list)) and len(t_tuple) >= 2:
            hh = int(t_tuple[0] or 0)
            mm = int(t_tuple[1] or 0)
        try:
            return datetime(int(d_tuple[0]), int(d_tuple[1]), int(d_tuple[2]), hh, mm, tzinfo=UTC)
        except ValueError:
            return None
    return None


def build_google_flights_url(
    legs: list[FlightLegOption],
    ticket_type: TicketType,
    baggage: BaggageConfig | None = None,
    stops_policy: StopsPolicy | None = None,
) -> str:
    """Build a Google Flights search URL for all supplied ticket legs.

    The link specifies one adult, USD, and the highest cabin across the legs.
    It encodes an exact two-leg reverse route as a round trip when requested;
    other multi-leg routes use multi-city search. It does not select exact
    flight numbers, book a ticket, or verify its availability or price.

    Args:
        legs: Ticket legs in the order they will be flown.
        ticket_type: Proposed ticket type used to choose the search shape.
        baggage: Optional carry-on and checked-bag search preferences.
        stops_policy: Optional connection limit used for layover filtering.
            The encoded limit also allows the candidate leg's average layover,
            rounded up to 30 minutes.

    Returns:
        A search URL, or the Google Flights home URL when no legs are given.

    Examples:
        Build a link without making a network request. This example uses a
        synthetic leg, not a bookable flight.

        >>> from datetime import date
        >>> from urllib.parse import parse_qs, urlparse
        >>> from backend.app.models.queries import LegSearch
        >>> from backend.app.models.schemas import ConcreteCabinClass, TicketType
        >>> from backend.app.providers.pricing_engine import RealisticPricingProvider
        >>> from backend.app.providers.google_flights import build_google_flights_url
        >>> build_google_flights_url([], TicketType.ONE_WAY)
        'https://www.google.com/travel/flights'
        >>> query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.ECONOMY)
        >>> leg = RealisticPricingProvider().search(query).options[0]
        >>> url = build_google_flights_url([leg], TicketType.ONE_WAY)
        >>> "tfs" in parse_qs(urlparse(url).query)
        True
    """
    if not legs:
        return "https://www.google.com/travel/flights"

    policy = stops_policy or StopsPolicy()
    policy_layover_mins = round(policy.max_layover_hours * 60.0)
    flight_queries: list[FlightQuery] = []
    for leg in legs:
        max_layover_mins: int | None = None
        if leg.stops_count > 0:
            per_stop_hrs = leg.layover_hours / leg.stops_count
            leg_layover_mins = math.ceil(per_stop_hrs * 60.0 / 30.0) * 30
            max_layover_mins = max(policy_layover_mins, leg_layover_mins)
        flight_queries.append(
            FlightQuery(
                date=leg.departure_date.isoformat(),
                from_airport=leg.origin.upper(),
                to_airport=leg.destination.upper(),
                max_stops=leg.stops_count,
                max_layover_minutes=max_layover_mins,
            )
        )

    is_exact_round_trip = (
        ticket_type == TicketType.ROUND_TRIP
        and len(legs) == 2
        and legs[0].origin.upper() == legs[1].destination.upper()
        and legs[0].destination.upper() == legs[1].origin.upper()
    )
    trip_str: Literal["one-way", "round-trip", "multi-city"] = (
        "one-way" if len(legs) == 1 else ("round-trip" if is_exact_round_trip else "multi-city")
    )
    top_cabin = max((leg.cabin for leg in legs), key=lambda c: _CABIN_ORDER[c], default=ConcreteCabinClass.ECONOMY)
    seat_str: SeatType = _SEAT_TYPE_MAP[top_cabin]
    trip_arg: TripType = trip_str

    q = create_query(
        flights=flight_queries,
        seat=seat_str,
        trip=trip_arg,
        passengers=Passengers(adults=1),
        language="en",
        currency="USD",
        carry_on_bags=1 if (baggage and baggage.include_carry_on) else 0,
        checked_bags=baggage.checked_bags if baggage else 0,
    )
    return q.url()


# Static carrier metadata used to supplement live responses. Bag fees are estimates.
AIRLINE_METADATA_BY_CODE: dict[str, tuple[str, bool, float]] = {
    c.code: (c.alliance, c.is_lcc, c.bag_fee_usd) for c in CARRIERS
}
AIRLINE_METADATA_BY_NAME: dict[str, tuple[str, str, bool, float]] = {
    c.name.lower(): (c.code, c.alliance, c.is_lcc, c.bag_fee_usd) for c in CARRIERS
}

# Manually maintained alliance and low-cost carrier rosters for carriers not
# listed in CARRIERS. Classifications can become outdated.
_ALLIANCE_ROSTERS: dict[str, tuple[str, ...]] = {
    "Star Alliance": (
        "A3",
        "AC",
        "AI",
        "AV",
        "BR",
        "CA",
        "CM",
        "ET",
        "EW",
        "LH",
        "LO",
        "LX",
        "MS",
        "NH",
        "NZ",
        "OS",
        "OU",
        "OZ",
        "SN",
        "SQ",
        "TG",
        "TK",
        "TP",
        "UA",
        "ZH",
    ),
    "Oneworld": (
        "AA",
        "AS",
        "AT",
        "AY",
        "BA",
        "CX",
        "EI",
        "FJ",
        "IB",
        "JL",
        "MH",
        "QF",
        "QR",
        "RJ",
        "UL",
        "WY",
    ),
    "SkyTeam": (
        "AF",
        "AM",
        "AR",
        "AZ",
        "CI",
        "DL",
        "GA",
        "KE",
        "KL",
        "KQ",
        "ME",
        "MU",
        "RO",
        "SK",
        "SV",
        "UX",
        "VN",
        "VS",
    ),
    "LCC": ("U2", "FR", "W6", "VY", "WN", "B6", "NK", "F9", "ZG", "AK", "TR", "GQ", "DY"),
}
ALLIANCE_BY_IATA_CODE: dict[str, str] = {
    code: alliance for alliance, codes in _ALLIANCE_ROSTERS.items() for code in codes
}

# Dynamically populated from Google Flights response metadata (e.g. ResultList.metadata.airlines and SerpApi flight_number)
DISCOVERED_AIRLINE_CODES_BY_NAME: dict[str, str] = {}


def register_discovered_airline(code: str, name: str) -> None:
    """Register a discovered airline name and two-character code in memory.

    Names are stored in lowercase and codes in uppercase. Ignore blank names
    and codes that are not two alphanumeric characters.
    """
    clean_code = code.strip().upper()
    clean_name = name.strip().lower()
    if len(clean_code) == 2 and clean_code.isalnum() and clean_name:
        DISCOVERED_AIRLINE_CODES_BY_NAME[clean_name] = clean_code


def resolve_airline_metadata(airline_code: str, airline_name: str) -> tuple[str, str, bool, float]:
    """Resolve carrier metadata from a live response's code or name.

    Prefer static code metadata, then alliance rosters and known or discovered
    names. Unknown carriers use a non-aligned classification and an estimated
    $45 checked-bag fee. When both a code and name are supplied, a valid pair
    is also registered in the process-wide discovered-airline map.

    Returns:
        A tuple of carrier code, alliance, low-cost flag, and estimated fee
        per checked bag in USD. These values are not a verified fare policy.

    Examples:
        >>> from backend.app.providers.google_flights import resolve_airline_metadata
        >>> resolve_airline_metadata("UA", "")
        ('UA', 'Star Alliance', False, 40.0)
    """
    code = airline_code.strip().upper()
    if code and airline_name:
        register_discovered_airline(code, airline_name)

    lower_name = airline_name.strip().lower()
    if not code and lower_name in DISCOVERED_AIRLINE_CODES_BY_NAME:
        code = DISCOVERED_AIRLINE_CODES_BY_NAME[lower_name]

    if code in AIRLINE_METADATA_BY_CODE:
        alliance, is_lcc, bag_fee = AIRLINE_METADATA_BY_CODE[code]
        return code, alliance, is_lcc, bag_fee

    if code in ALLIANCE_BY_IATA_CODE:
        alliance = ALLIANCE_BY_IATA_CODE[code]
        is_lcc = alliance == "LCC"
        return code, alliance, is_lcc, (50.0 if is_lcc else 40.0)

    for known_name, (k_code, alliance, is_lcc, bag_fee) in AIRLINE_METADATA_BY_NAME.items():
        if known_name in lower_name or (lower_name and lower_name in known_name):
            return (code or k_code), alliance, is_lcc, bag_fee

    for disc_name, disc_code in DISCOVERED_AIRLINE_CODES_BY_NAME.items():
        if disc_name in lower_name or (lower_name and lower_name in disc_name):
            alliance = ALLIANCE_BY_IATA_CODE.get(disc_code, "Non-Aligned")
            is_lcc = alliance == "LCC"
            return (code or disc_code), alliance, is_lcc, (50.0 if is_lcc else 40.0)

    fallback_code = code if len(code) == 2 else (airline_name[:2].upper() if airline_name else "FL")
    return fallback_code, "Non-Aligned", False, 45.0


class _LiveQueryBudgetExceeded(Exception):
    """Signal that a retry cannot run within the live-query budget."""


class _ProviderResponseError(Exception):
    """Signal an invalid or rejected response from a live provider."""


class CompositeFlightProvider(FlightSearchProvider):
    """Search fast-flights, SerpApi, or a test-only simulated provider.

    Fast-flights searches selected airport pairs. SerpApi first batches the
    selected airports and can retry individual pairs. Auto mode tries
    fast-flights first and can use SerpApi when it is configured. Live modes
    never fall back to simulated flights. Offline mode requires
    ``FARESPLIT_TESTING=1`` for a nonempty search.

    Args:
        cache: Optional cache used to record live-provider usage. Search-result
            caching requires a separate ``CachedFlightProvider`` wrapper.
        mode: Provider mode to use.
        max_api_calls: Maximum live queries, including retries, for a run.
        rate_limit_seconds: Minimum delay between live calls. If omitted, use
            ``FLIGHT_SEARCH_DELAY_SECONDS`` or the backend-specific default.

    Examples:
        >>> from backend.app.models.schemas import ProviderMode
        >>> from backend.app.providers.google_flights import CompositeFlightProvider
        >>> provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS, rate_limit_seconds=0)
        >>> provider.is_simulation(), provider.api_calls_this_run
        (False, 0)
    """

    def __init__(
        self,
        cache: FlightCache | None = None,
        mode: ProviderMode = ProviderMode.AUTO,
        max_api_calls: int = 25,
        rate_limit_seconds: float | None = None,
    ) -> None:
        """Initialize provider settings without making a live search."""
        load_dotenv()
        self.serpapi_key = os.environ.get("SERPAPI_KEY", "").strip()
        self.cache = cache
        self.mode = mode
        self.max_api_calls = max_api_calls
        self.max_layover_hours = StopsPolicy().max_layover_hours
        env_delay = os.environ.get("FLIGHT_SEARCH_DELAY_SECONDS", "").strip()
        self.rate_limit_seconds = (
            rate_limit_seconds if rate_limit_seconds is not None else (float(env_delay) if env_delay else None)
        )
        self.fallback = RealisticPricingProvider()
        self.api_calls_this_run = 0
        self._last_request_ts = 0.0

    def is_simulation(self) -> bool:
        """Return whether the configured mode uses simulated flights."""
        return self.mode == ProviderMode.OFFLINE

    def cache_scope(self) -> str:
        """Identify the mode and effective layover limit for cache isolation."""
        effective_layover = max(self.max_layover_hours, StopsPolicy().max_layover_hours)
        return f"google-flights:{self.mode.value}:layover={effective_layover:g}"

    def configure_for_run(
        self,
        cache: FlightCache,
        mode: ProviderMode,
        max_api_calls: int,
        stops_policy: StopsPolicy | None = None,
    ) -> None:
        """Configure a new run and reset its live-query counter.

        This refreshes the SerpApi key from the environment, updates the
        cache's active-provider label, and applies the requested layover
        policy. Configure the provider before constructing its cache wrapper.

        Args:
            cache: Cache used to track provider calls.
            mode: Provider mode for the run.
            max_api_calls: Maximum live queries, including retries.
            stops_policy: Optional maximum layover policy.

        Raises:
            ValueError: If offline mode is selected without
                ``FARESPLIT_TESTING=1``.
        """
        load_dotenv()
        self.serpapi_key = os.environ.get("SERPAPI_KEY", "").strip()
        self.cache = cache
        self.mode = mode
        self.max_api_calls = max_api_calls
        self.max_layover_hours = (stops_policy or StopsPolicy()).max_layover_hours
        self.api_calls_this_run = 0
        cache.active_provider = mode.value
        if mode == ProviderMode.OFFLINE and os.environ.get("FARESPLIT_TESTING") != "1":
            raise ValueError("Simulated flights are only available when FARESPLIT_TESTING=1.")

    def _throttle(self, default_delay: float) -> None:
        """Wait for the minimum interval between live requests, in seconds."""
        delay = self.rate_limit_seconds if self.rate_limit_seconds is not None else default_delay
        if delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        if self._last_request_ts > 0 and elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_ts = time.monotonic()

    def _can_make_live_call(self) -> bool:
        """Return whether the run has remaining live-query budget."""
        return self.api_calls_this_run < self.max_api_calls

    def _budget_issue(self) -> SearchIssue:
        """Describe the exhausted live-query budget for a search result."""
        return SearchIssue(
            SearchIssueKind.BUDGET_EXHAUSTED,
            f"Reached per-run live API limit ({self.max_api_calls} queries). "
            "Some searches were incomplete; run Optimize again to fetch more live legs.",
        )

    def _attempt(self, query: LegSearch, backend: Literal["fast_flights", "serpapi"]) -> SearchResult:
        """Run one backend search and classify recognized provider failures.

        Exhausting the budget before a call fails the search. Exhausting it
        during a retry reports a partial search. Unexpected programming
        errors propagate rather than being reported as provider failures.
        """
        if not self._can_make_live_call():
            return SearchResult(status=SearchStatus.FAILED, issues=(self._budget_issue(),))

        origins = ",".join(query.origins)
        destinations = ",".join(query.destinations)
        try:
            if backend == "fast_flights":
                options = self._search_fast_flights(origins, destinations, query.departure_date, query.cabin)
            else:
                options = self._search_serpapi_google_flights(origins, destinations, query.departure_date, query.cabin)
        except _LiveQueryBudgetExceeded:
            return SearchResult(status=SearchStatus.PARTIAL, issues=(self._budget_issue(),))
        except (PrimpError, httpx.HTTPError, FlightsNotFound, json.JSONDecodeError, _ProviderResponseError) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                detail = f"HTTP {exc.response.status_code}"
            elif isinstance(exc, _ProviderResponseError):
                detail = str(exc)
            else:
                detail = type(exc).__name__
            label = "fast-flights" if backend == "fast_flights" else "SerpApi"
            issue = SearchIssue(
                SearchIssueKind.PROVIDER_ERROR,
                f"{label} query ({origins}→{destinations} on {query.departure_date}) failed: {detail}.",
            )
            return SearchResult(status=SearchStatus.FAILED, issues=(issue,))
        return SearchResult(options=tuple(options))

    @staticmethod
    def _has_budget_issue(result: SearchResult) -> bool:
        """Return whether a result reports an exhausted live-query budget."""
        return any(issue.kind == SearchIssueKind.BUDGET_EXHAUSTED for issue in result.issues)

    @staticmethod
    def _combine_pairs(pair_results: list[SearchResult], batch_result: SearchResult | None = None) -> SearchResult:
        """Combine pair results and retain issues from incomplete searches.

        If all pair searches complete, a recovered batch failure is logged
        instead of returned as a search issue.
        """
        options = tuple(option for result in pair_results for option in result.options)
        issues = [issue for result in pair_results for issue in result.issues]
        pairs_complete = all(result.status == SearchStatus.COMPLETE for result in pair_results)
        if batch_result is not None and pairs_complete:
            for issue in batch_result.issues:
                _LOGGER.warning("Recovered batched search failure after searching airport pairs: %s", issue.message)
        elif batch_result is not None:
            issues = [*batch_result.issues, *issues]
        if pairs_complete:
            status = SearchStatus.COMPLETE
        elif any(result.status != SearchStatus.FAILED for result in pair_results) or (
            batch_result is not None and batch_result.status != SearchStatus.FAILED
        ):
            status = SearchStatus.PARTIAL
        else:
            status = SearchStatus.FAILED
        return SearchResult(options=options, status=status, issues=tuple(issues))

    def search(self, query: LegSearch) -> SearchResult:
        """Search the selected airport pairs with the configured provider.

        Pairs with identical endpoints are skipped. Fast-flights and auto
        search the remaining pairs until the budget is exhausted. SerpApi
        first searches the airports as a batch and may retry individual pairs
        when that search returns no options. A query with no distinct pair
        returns a complete empty result.

        Args:
            query: Selected airports, departure date, and cabin.

        Returns:
            Candidate options, completion status, and provider or budget issues.

        Raises:
            ValueError: If the mode is unsupported or an offline search with
                a distinct pair is requested without ``FARESPLIT_TESTING=1``.
        """
        origins = query.origins
        destinations = query.destinations
        departure_date = query.departure_date
        cabin = query.cabin
        pairs = [(orig, dest) for orig in origins for dest in destinations if orig != dest]
        if not pairs:
            return SearchResult()

        if self.mode == ProviderMode.OFFLINE:
            if os.environ.get("FARESPLIT_TESTING") != "1":
                raise ValueError("Simulated flights are only available when FARESPLIT_TESTING=1.")
            return self.fallback.search(query)

        if self.mode == ProviderMode.SERPAPI:
            if not self.serpapi_key:
                issue = SearchIssue(
                    SearchIssueKind.MISSING_CREDENTIALS,
                    "SERPAPI mode selected, but SERPAPI_KEY is not set in .env or environment.",
                )
                return SearchResult(status=SearchStatus.FAILED, issues=(issue,))
            batch = self._attempt(query, "serpapi")
            if batch.options or len(origins) == len(destinations) == 1 or self._has_budget_issue(batch):
                return batch
            pair_results: list[SearchResult] = []
            for orig, dest in pairs:
                result = self._search_pair(LegSearch.single(orig, dest, departure_date, cabin))
                pair_results.append(result)
                if self._has_budget_issue(result):
                    break
            return self._combine_pairs(pair_results, batch)

        if self.mode in (ProviderMode.FAST_FLIGHTS, ProviderMode.AUTO):
            pair_results = []
            for orig, dest in pairs:
                result = self._search_pair(LegSearch.single(orig, dest, departure_date, cabin))
                pair_results.append(result)
                if self._has_budget_issue(result):
                    break
            return self._combine_pairs(pair_results)

        raise ValueError(f"Unsupported flight provider mode: {self.mode}")

    def _search_pair(self, query: LegSearch) -> SearchResult:
        """Search one pair and use SerpApi after an eligible auto-mode failure.

        A recovered fast-flights failure is logged rather than included in
        the successful SerpApi result.
        """
        fast: SearchResult | None = None
        if self.mode in (ProviderMode.FAST_FLIGHTS, ProviderMode.AUTO):
            fast = self._attempt(query, "fast_flights")
            if fast.options or self.mode == ProviderMode.FAST_FLIGHTS or self._has_budget_issue(fast):
                return fast
            if not self.serpapi_key:
                return fast

        serp = self._attempt(query, "serpapi")
        if fast is None:
            return serp
        issues = (*fast.issues, *serp.issues)
        if serp.status == SearchStatus.COMPLETE:
            for issue in fast.issues:
                _LOGGER.warning("Recovered fast-flights failure with SerpApi: %s", issue.message)
            return SearchResult(options=serp.options, issues=serp.issues)
        status = SearchStatus.PARTIAL if fast.status != SearchStatus.FAILED else serp.status
        return SearchResult(options=serp.options, status=status, issues=issues)

    def _search_fast_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Fetch fast-flights options, retrying once without a layover cap.

        The retry occurs only when the first response is empty and budget
        remains. Each fetch counts against the live-query budget.
        """
        self._throttle(default_delay=1.0)
        self.api_calls_this_run += 1
        if self.cache is not None:
            self.cache.record_provider_call("fast_flights")
            self.cache.active_provider = "fast_flights"

        def _fetch_results(layover_limit: int | None) -> list[Any]:
            """Fetch and parse HTML, recording responses when enabled or invalid."""
            query = create_query(
                flights=[
                    FlightQuery(
                        date=departure_date.isoformat(),
                        from_airport=origin.upper(),
                        to_airport=destination.upper(),
                        max_layover_minutes=layover_limit,
                    )
                ],
                seat=_SEAT_TYPE_MAP[cabin],
                trip="one-way",
                passengers=Passengers(adults=1),
                currency="USD",
                language="en",
                hide_separate_and_self_transfer=True,
            )
            html = fetch_flights_html(query)
            try:
                results = parse_fast_flights_html(html)
            except FlightsNotFound:
                record_provider_response(
                    "fast_flights",
                    {
                        "origin": origin.upper(),
                        "destination": destination.upper(),
                        "departure_date": departure_date.isoformat(),
                        "cabin": cabin.value,
                    },
                    html,
                )
                raise
            except (IndexError, TypeError, AttributeError, KeyError, ValueError) as exc:
                record_provider_response(
                    "fast_flights",
                    {
                        "origin": origin.upper(),
                        "destination": destination.upper(),
                        "departure_date": departure_date.isoformat(),
                        "cabin": cabin.value,
                    },
                    html,
                    parse_error=exc,
                )
                raise _ProviderResponseError(f"unable to parse response ({type(exc).__name__})") from exc
            record_provider_response(
                "fast_flights",
                {
                    "origin": origin.upper(),
                    "destination": destination.upper(),
                    "departure_date": departure_date.isoformat(),
                    "cabin": cabin.value,
                },
                html,
            )
            return results

        default_cap_hours = StopsPolicy().max_layover_hours
        effective_hours = max(self.max_layover_hours, default_cap_hours)
        layover_mins = round(effective_hours * 60.0) if effective_hours > 0 else None
        result_list = _fetch_results(layover_mins)

        # If strict layover cap yielded no flights on this corridor, retry without the layover cap
        if not result_list and layover_mins is not None:
            if not self._can_make_live_call():
                raise _LiveQueryBudgetExceeded
            self._throttle(default_delay=1.0)
            self.api_calls_this_run += 1
            if self.cache is not None:
                self.cache.record_provider_call("fast_flights")
            result_list = _fetch_results(None)

        return self.parse_fast_flights_results(
            results=result_list,
            origin=origin.upper(),
            destination=destination.upper(),
            departure_date=departure_date,
            cabin=cabin,
        )

    @staticmethod
    def _compute_fast_flights_layovers(raw_flights: list[Any]) -> list[float]:
        """Compute layover hours between consecutive fast-flights segments.

        Subtract the local arrival and departure wall times at each connection.
        Missing dates, invalid calendar values, and negative differences use
        an estimated 1.75 hours for that connection. A time component that
        cannot be converted to an integer can raise an error.
        """
        if len(raw_flights) <= 1:
            return []
        layovers: list[float] = []
        for prev_sf, next_sf in itertools.pairwise(raw_flights):
            arr_dt = _extract_simple_datetime(getattr(prev_sf, "arrival", None))
            dep_dt = _extract_simple_datetime(getattr(next_sf, "departure", None))
            if arr_dt is not None and dep_dt is not None:
                diff_hrs = round((dep_dt - arr_dt).total_seconds() / 3600.0, 2)
                if diff_hrs >= 0:
                    layovers.append(diff_hrs)
                    continue
            layovers.append(1.75)
        return layovers

    @staticmethod
    def _select_diverse_by_stops(
        options: list[FlightLegOption],
        max_total: int = 15,
    ) -> list[FlightLegOption]:
        """Rank options while sampling nonstop, one-stop, and two-plus-stop buckets.

        Take up to five from each bucket before filling remaining slots. Rank
        normal connections ahead of those over the default average layover
        limit, then by one-way fare plus $35 per layover hour and duration.
        Sort the final selection by that rank and return at most ``max_total``.
        """
        default_cap = StopsPolicy().max_layover_hours

        def rank_key(opt: FlightLegOption) -> tuple[bool, float, float]:
            """Rank excessive layovers after normal connections."""
            over_cap = opt.stops_count > 0 and (opt.layover_hours / opt.stops_count) > default_cap
            return (over_cap, opt.one_way_base_fare_usd + opt.layover_hours * 35.0, opt.duration_hours)

        buckets: dict[int, list[FlightLegOption]] = {0: [], 1: [], 2: []}
        for opt in options:
            buckets[min(2, max(0, opt.stops_count))].append(opt)

        for bucket in buckets.values():
            bucket.sort(key=rank_key)

        selected: list[FlightLegOption] = []
        # Take up to 5 from each bucket first (prioritizing nonstop and 1-stop)
        for s in (0, 1, 2):
            selected.extend(buckets[s][:5])
        if len(selected) < max_total:
            pool = [o for s in (0, 1, 2) for o in buckets[s] if o not in selected]
            pool.sort(key=rank_key)
            selected.extend(pool[: max_total - len(selected)])
        selected.sort(key=rank_key)
        return selected[:max_total]

    @staticmethod
    def parse_fast_flights_results(
        results: list[Any],
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Convert parsed fast-flights results into candidate leg options.

        Skip results without a nonzero price or segments and return up to 15 ranked
        options. Airline and airport discoveries and observed durations are
        registered in process-wide metadata. Flight numbers are synthesized;
        round-trip half-fares and baggage details are estimates.

        Args:
            results: Parsed fast-flights results, optionally with metadata.
            origin: Fallback origin when a segment lacks an airport code.
            destination: Fallback destination when a segment lacks a code.
            departure_date: Requested date, also used for missing segment dates.
            cabin: Requested cabin for the candidate legs.

        Returns:
            Normalized candidate options. This parser does not fetch flights.

        Examples:
            >>> from datetime import date
            >>> from backend.app.models.schemas import ConcreteCabinClass
            >>> from backend.app.providers.google_flights import CompositeFlightProvider
            >>> CompositeFlightProvider.parse_fast_flights_results(
            ...     [], "SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.ECONOMY
            ... )
            []
        """
        if not results:
            return []

        # Extract airline code -> name mappings directly from Google Flights response metadata
        meta = getattr(results, "metadata", None)
        airlines_meta: list[Any] = getattr(meta, "airlines", None) or []
        for airline_meta in airlines_meta:
            m_code = str(getattr(airline_meta, "code", "") or "")
            m_name = str(getattr(airline_meta, "name", "") or "")
            if m_code and m_name:
                register_discovered_airline(m_code, m_name)

        options: list[FlightLegOption] = []
        for idx, item in enumerate(results):
            price_val = getattr(item, "price", None)
            raw_flights: list[Any] = getattr(item, "flights", None) or []
            airlines_list: list[Any] = getattr(item, "airlines", None) or []
            if not price_val or not raw_flights:
                continue

            ow_price = float(price_val)
            primary_airline_name = str(airlines_list[0]) if airlines_list else "Airline"
            raw_type = str(getattr(item, "type", "") or "").strip().upper()
            type_code = raw_type if len(raw_type) == 2 and raw_type.isalnum() else ""
            carrier_code, alliance, is_lcc, bag_fee = resolve_airline_metadata(type_code, primary_airline_name)
            if len(airlines_list) > 1:
                resolved_all = [resolve_airline_metadata("", str(a)) for a in airlines_list if str(a).strip()]
                alliances_set = {r[1] for r in resolved_all}
                if any(r[2] for r in resolved_all):
                    is_lcc = True
                    alliance = "LCC"
                elif len(alliances_set) > 1:
                    alliance = "Non-Aligned"
            if not is_lcc and cabin in (ConcreteCabinClass.BUSINESS, ConcreteCabinClass.FIRST):
                bag_fee = 0.0

            segments: list[FlightSegment] = []
            flight_numbers: list[str] = []
            for seg_idx, sf in enumerate(raw_flights):
                from_ap = getattr(sf, "from_airport", None)
                to_ap = getattr(sf, "to_airport", None)
                dep_code = str(getattr(from_ap, "code", "") or origin)
                arr_code = str(getattr(to_ap, "code", "") or destination)
                register_discovered_airport(dep_code, str(getattr(from_ap, "name", "") or ""))
                register_discovered_airport(arr_code, str(getattr(to_ap, "name", "") or ""))
                dep_dt_obj = getattr(sf, "departure", None)
                arr_dt_obj = getattr(sf, "arrival", None)
                dep_parsed_dt = _extract_simple_datetime(dep_dt_obj)
                arr_parsed_dt = _extract_simple_datetime(arr_dt_obj)
                seg_dep_date = dep_parsed_dt.date() if dep_parsed_dt is not None else departure_date
                seg_arr_date = arr_parsed_dt.date() if arr_parsed_dt is not None else None
                dep_time_tuple = getattr(dep_dt_obj, "time", (9, 0))
                arr_time_tuple = getattr(arr_dt_obj, "time", (17, 0))
                dep_hm = f"{int(dep_time_tuple[0]):02d}:{int(dep_time_tuple[1]):02d}"
                arr_hm = f"{int(arr_time_tuple[0]):02d}:{int(arr_time_tuple[1]):02d}"
                dur_min = float(getattr(sf, "duration", 60) or 60)
                seg_dur_hrs = round(dur_min / 60.0, 2)
                record_observed_duration(dep_code, arr_code, seg_dur_hrs)
                fn_code = f"{carrier_code}{100 + idx * 10 + seg_idx}"
                flight_numbers.append(fn_code)

                segments.append(
                    FlightSegment(
                        origin=dep_code,
                        destination=arr_code,
                        departure_date=seg_dep_date,
                        departure_time=dep_hm,
                        arrival_date=seg_arr_date,
                        arrival_time=arr_hm,
                        airline=carrier_code,
                        airline_name=primary_airline_name,
                        alliance=alliance,
                        flight_number=fn_code,
                        duration_hours=seg_dur_hrs,
                        cabin=cabin,
                        aircraft=str(getattr(sf, "plane_type", "Jet") or "Jet"),
                    )
                )

            actual_orig = segments[0].origin
            actual_dest = segments[-1].destination
            stops_count = max(0, len(segments) - 1)
            layover_airports = [s.destination for s in segments[:-1]]
            flight_hrs = round(sum(s.duration_hours for s in segments), 2)
            record_observed_duration(actual_orig, actual_dest, flight_hrs)
            layovers_list = CompositeFlightProvider._compute_fast_flights_layovers(raw_flights)
            layover_hours = round(sum(layovers_list), 2)
            total_hours = round(flight_hrs + layover_hours, 2)
            rt_half = ow_price if is_lcc else round(ow_price * 0.76, 2)

            leg_id = f"{actual_orig}-{actual_dest}-{departure_date.isoformat()}-{carrier_code}-ff{idx}-{cabin.value}"
            options.append(
                FlightLegOption(
                    leg_id=leg_id,
                    origin=actual_orig,
                    destination=actual_dest,
                    departure_date=departure_date,
                    cabin=cabin,
                    airline=carrier_code,
                    airline_name=primary_airline_name,
                    alliance=alliance,
                    flight_numbers=flight_numbers,
                    segments=segments,
                    duration_hours=total_hours,
                    stops_count=stops_count,
                    layover_airports=layover_airports,
                    layover_hours=layover_hours,
                    one_way_base_fare_usd=round(ow_price, 2),
                    round_trip_half_fare_usd=rt_half,
                    bag_fee_per_checked_bag_usd=bag_fee,
                    includes_carry_on=True,
                    is_lcc=is_lcc,
                    provider="fast_flights",
                    from_cache=False,
                )
            )

        return CompositeFlightProvider._select_diverse_by_stops(options)

    def _search_serpapi_google_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Fetch and parse one SerpApi request, which may batch airport codes."""
        cabin_map = {
            ConcreteCabinClass.ECONOMY: "1",
            ConcreteCabinClass.PREMIUM_ECONOMY: "2",
            ConcreteCabinClass.BUSINESS: "3",
            ConcreteCabinClass.FIRST: "4",
        }
        self._throttle(default_delay=0.4)
        self.api_calls_this_run += 1
        if self.cache is not None:
            self.cache.record_provider_call("serpapi")
            self.cache.active_provider = "serpapi"

        params = {
            "engine": "google_flights",
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "outbound_date": departure_date.isoformat(),
            "type": "2",  # One-way
            "travel_class": cabin_map[cabin],
            "currency": "USD",
            "hl": "en",
            "api_key": self.serpapi_key,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.get("https://serpapi.com/search.json", params=params)
            resp.raise_for_status()
            body = resp.text
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            record_provider_response(
                "serpapi",
                {
                    "origin": origin.upper(),
                    "destination": destination.upper(),
                    "departure_date": departure_date.isoformat(),
                    "cabin": cabin.value,
                },
                body,
                parse_error=exc,
            )
            raise

        query = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_date": departure_date.isoformat(),
            "cabin": cabin.value,
        }

        if not isinstance(data, dict):
            record_provider_response("serpapi", query, body, parse_error=ValueError("expected JSON object"))
            raise _ProviderResponseError("invalid response")
        if data.get("error"):
            record_provider_response("serpapi", query, body)
            raise _ProviderResponseError("provider returned an error response")

        try:
            options = self.parse_google_flights_payload(
                data=data,
                origin=origin.upper(),
                destination=destination.upper(),
                departure_date=departure_date,
                cabin=cabin,
            )
        except (IndexError, TypeError, AttributeError, KeyError, ValueError) as exc:
            record_provider_response("serpapi", query, body, parse_error=exc)
            raise
        record_provider_response("serpapi", query, body)
        return options

    @staticmethod
    def parse_google_flights_payload(
        data: dict[str, Any],
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Parse a SerpApi Google Flights payload into candidate leg options.

        Combine the best and other result groups, skipping entries without a
        price or segments. Missing fields can use fallback airports, times,
        durations, or flight numbers. Round-trip half-fares and baggage details
        are estimates. Register discovered airlines, airports, and observed
        durations in process-wide metadata.

        Args:
            data: Decoded SerpApi JSON object.
            origin: Requested origin codes; the first is used as a fallback.
            destination: Requested destination codes; the first is a fallback.
            departure_date: Requested date, also used for missing segment dates.
            cabin: Requested cabin for the candidate legs.

        Returns:
            Up to 15 ranked candidate options. This parser makes no network
            request and does not verify the resulting ticket prices.

        Examples:
            >>> from datetime import date
            >>> from backend.app.models.schemas import ConcreteCabinClass
            >>> from backend.app.providers.google_flights import CompositeFlightProvider
            >>> CompositeFlightProvider.parse_google_flights_payload(
            ...     {}, "SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.ECONOMY
            ... )
            []
        """
        best_raw: list[dict[str, Any]] = data.get("best_flights") or []
        other_raw: list[dict[str, Any]] = data.get("other_flights") or []
        flights_raw: list[dict[str, Any]] = best_raw + other_raw
        if not flights_raw:
            return []

        fallback_orig = origin.split(",", maxsplit=1)[0].strip().upper()
        fallback_dest = destination.split(",", maxsplit=1)[0].strip().upper()

        parsed_options: list[FlightLegOption] = []
        for idx, item in enumerate(flights_raw):
            price_raw = item.get("price")
            if price_raw is None:
                continue
            ow_price = float(price_raw)
            total_duration_min = float(item.get("total_duration") or 0.0)
            raw_segments: list[dict[str, Any]] = item.get("flights") or []
            raw_layovers: list[dict[str, Any]] = item.get("layovers") or []
            if not raw_segments:
                continue

            first_seg = raw_segments[0]
            raw_fn = str(first_seg.get("flight_number") or "").replace(" ", "")
            raw_airline_name = str(first_seg.get("airline") or "Airline")
            raw_code = raw_fn[:2] if len(raw_fn) >= 2 else ""

            carrier_code, alliance, is_lcc, bag_fee = resolve_airline_metadata(raw_code, raw_airline_name)
            if not is_lcc and cabin in (ConcreteCabinClass.BUSINESS, ConcreteCabinClass.FIRST):
                bag_fee = 0.0

            segments: list[FlightSegment] = []
            flight_numbers: list[str] = []
            for seg in raw_segments:
                dep_info: dict[str, Any] = seg.get("departure_airport") or {}
                arr_info: dict[str, Any] = seg.get("destination_airport") or seg.get("arrival_airport") or {}
                dep_airport = str(dep_info.get("id") or fallback_orig)
                arr_airport = str(arr_info.get("id") or fallback_dest)
                register_discovered_airport(dep_airport, str(dep_info.get("name") or ""))
                register_discovered_airport(arr_airport, str(arr_info.get("name") or ""))
                dep_time_full = str(dep_info.get("time") or "09:00")
                arr_time_full = str(arr_info.get("time") or "17:00")
                dep_date_part = dep_time_full.split(" ", maxsplit=1)[0]
                arr_date_part = arr_time_full.split(" ", maxsplit=1)[0]
                try:
                    seg_dep_date = date.fromisoformat(dep_date_part)
                except ValueError:
                    seg_dep_date = departure_date
                try:
                    seg_arr_date: date | None = date.fromisoformat(arr_date_part)
                except ValueError:
                    seg_arr_date = None
                dep_hm = dep_time_full.rsplit(" ", maxsplit=1)[-1][:5]
                arr_hm = arr_time_full.rsplit(" ", maxsplit=1)[-1][:5]
                seg_dur_hrs = round(float(seg.get("duration") or 60.0) / 60.0, 2)
                record_observed_duration(dep_airport, arr_airport, seg_dur_hrs)
                fn_clean = str(seg.get("flight_number") or f"{carrier_code}{100 + idx}").replace(" ", "")
                flight_numbers.append(fn_clean)

                segments.append(
                    FlightSegment(
                        origin=dep_airport,
                        destination=arr_airport,
                        departure_date=seg_dep_date,
                        departure_time=dep_hm,
                        arrival_date=seg_arr_date,
                        arrival_time=arr_hm,
                        airline=carrier_code,
                        airline_name=raw_airline_name,
                        alliance=alliance,
                        flight_number=fn_clean,
                        duration_hours=seg_dur_hrs,
                        cabin=cabin,
                        aircraft=str(seg.get("airplane") or "Jet"),
                    )
                )

            for lay in raw_layovers:
                lay_id = str(lay.get("id") or "")
                if lay_id:
                    register_discovered_airport(lay_id, str(lay.get("name") or ""))

            actual_orig = segments[0].origin
            actual_dest = segments[-1].destination
            layover_airports = [str(lay.get("id")) for lay in raw_layovers if lay.get("id")]
            if not layover_airports and len(segments) > 1:
                layover_airports = [s.destination for s in segments[:-1]]

            flight_hrs = round(sum(s.duration_hours for s in segments), 2)
            record_observed_duration(actual_orig, actual_dest, flight_hrs)
            layover_hours = round(sum(float(lay.get("duration") or 0.0) for lay in raw_layovers) / 60.0, 2)
            total_hours = (
                round(total_duration_min / 60.0, 2) if total_duration_min > 0 else round(flight_hrs + layover_hours, 2)
            )
            stops_count = max(0, len(segments) - 1)

            rt_half = ow_price if is_lcc else round(ow_price * 0.76, 2)
            leg_id = (
                f"{actual_orig}-{actual_dest}-{departure_date.isoformat()}-"
                f"{carrier_code}-{'_'.join(flight_numbers)}-{cabin.value}"
            )

            parsed_options.append(
                FlightLegOption(
                    leg_id=leg_id,
                    origin=actual_orig,
                    destination=actual_dest,
                    departure_date=departure_date,
                    cabin=cabin,
                    airline=carrier_code,
                    airline_name=raw_airline_name,
                    alliance=alliance,
                    flight_numbers=flight_numbers,
                    segments=segments,
                    duration_hours=total_hours,
                    stops_count=stops_count,
                    layover_airports=layover_airports,
                    layover_hours=layover_hours,
                    one_way_base_fare_usd=round(ow_price, 2),
                    round_trip_half_fare_usd=rt_half,
                    bag_fee_per_checked_bag_usd=bag_fee,
                    includes_carry_on=True,
                    is_lcc=is_lcc,
                    provider="serpapi",
                    from_cache=False,
                )
            )

        return CompositeFlightProvider._select_diverse_by_stops(parsed_options)
