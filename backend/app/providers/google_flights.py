"""Pluggable provider adapter supporting fast-flights (free scraper), SerpApi (batched), and offline simulation."""

from __future__ import annotations

import itertools
import json
import math
import os
import time
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from fast_flights import FlightQuery, FlightsNotFound, Passengers, create_query, get_flights
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

load_dotenv()

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
    """Extract a naive local datetime from a fast_flights `SimpleDatetime(date=(Y, M, D), time=(H, M))`."""
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
    """Build a direct Google Flights search URL (`?tfs=...`) pre-populated with all slices,
    dates, cabin class, stop limits, max layover duration, and baggage for a bookable ticket.
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


# Lookup table mapping 2-letter IATA airline code or airline name to (alliance, is_lcc, bag_fee_usd).
# Used ONLY to enrich live Google Flights responses when alliance metadata isn't in the payload.
AIRLINE_METADATA_BY_CODE: dict[str, tuple[str, bool, float]] = {
    c.code: (c.alliance, c.is_lcc, c.bag_fee_usd) for c in CARRIERS
}
AIRLINE_METADATA_BY_NAME: dict[str, tuple[str, str, bool, float]] = {
    c.name.lower(): (c.code, c.alliance, c.is_lcc, c.bag_fee_usd) for c in CARRIERS
}

# Minimal IATA 2-letter alliance & LCC rosters so live Google Flights carriers are tagged
# accurately without hardcoding hub/route profiles in CARRIERS.
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
    """Register an airline's 2-letter IATA code and display name extracted from a flight search response."""
    clean_code = code.strip().upper()
    clean_name = name.strip().lower()
    if len(clean_code) == 2 and clean_code.isalnum() and clean_name:
        DISCOVERED_AIRLINE_CODES_BY_NAME[clean_name] = clean_code


def resolve_airline_metadata(airline_code: str, airline_name: str) -> tuple[str, str, bool, float]:
    """Return (code, alliance, is_lcc, default_bag_fee) from live carrier code or name."""
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
    pass


class _ProviderResponseError(Exception):
    pass


class CompositeFlightProvider(FlightSearchProvider):
    """Multi-mode flight provider supporting:
    - `fast_flights`: Free live Google Flights protobuf scraping with proactive rate-limiting.
    - `serpapi`: Official SerpApi Google Flights JSON API with multi-airport comma batching & quota cap.
    - `auto`: Uses `fast_flights` first (0 SerpApi quota), falling back to `serpapi` if needed.
    - `offline`: Test-only local simulation (`RealisticPricingProvider`); requires FARESPLIT_TESTING=1.
    """

    def __init__(
        self,
        cache: FlightCache | None = None,
        mode: ProviderMode = ProviderMode.AUTO,
        max_api_calls: int = 25,
        rate_limit_seconds: float | None = None,
    ) -> None:
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
        return self.mode == ProviderMode.OFFLINE

    def cache_scope(self) -> str:
        effective_layover = max(self.max_layover_hours, StopsPolicy().max_layover_hours)
        return f"google-flights:{self.mode.value}:layover={effective_layover:g}"

    def configure_for_run(
        self,
        cache: FlightCache,
        mode: ProviderMode,
        max_api_calls: int,
        stops_policy: StopsPolicy | None = None,
    ) -> None:
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
        delay = self.rate_limit_seconds if self.rate_limit_seconds is not None else default_delay
        if delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        if self._last_request_ts > 0 and elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_ts = time.monotonic()

    def _can_make_live_call(self) -> bool:
        return self.api_calls_this_run < self.max_api_calls

    def _budget_issue(self) -> SearchIssue:
        return SearchIssue(
            SearchIssueKind.BUDGET_EXHAUSTED,
            f"Reached per-run live API limit ({self.max_api_calls} queries). "
            "Some searches were incomplete; run Optimize again to fetch more live legs.",
        )

    def _attempt(self, query: LegSearch, backend: Literal["fast_flights", "serpapi"]) -> SearchResult:
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
        return any(issue.kind == SearchIssueKind.BUDGET_EXHAUSTED for issue in result.issues)

    @staticmethod
    def _combine_pairs(
        query: LegSearch,
        pair_results: list[SearchResult],
        pair_count: int,
        batch_result: SearchResult | None = None,
    ) -> SearchResult:
        options = tuple(option for result in pair_results for option in result.options)
        issues = [issue for result in pair_results for issue in result.issues]
        if batch_result is not None:
            issues = [*batch_result.issues, *issues]
        skipped = pair_count - len(pair_results)
        if skipped and not any(issue.kind == SearchIssueKind.BUDGET_EXHAUSTED for issue in issues):
            issues.append(
                SearchIssue(
                    SearchIssueKind.TRUNCATED,
                    f"Search ({','.join(query.origins)}→{','.join(query.destinations)} on {query.departure_date}) "
                    f"covered {len(pair_results)} of {pair_count} airport pairs; other pairs were not searched.",
                )
            )
        if not skipped and all(result.status == SearchStatus.COMPLETE for result in pair_results):
            status = SearchStatus.COMPLETE
        elif any(result.status != SearchStatus.FAILED for result in pair_results) or (
            batch_result is not None and batch_result.status != SearchStatus.FAILED
        ):
            status = SearchStatus.PARTIAL
        else:
            status = SearchStatus.FAILED
        return SearchResult(options=options, status=status, issues=tuple(issues))

    def search(self, query: LegSearch) -> SearchResult:
        """Batch multiple origins and destinations into a single query when using SerpApi,
        or query primary airport pairs when using fast-flights to conserve requests.
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
            return self._combine_pairs(query, pair_results, len(pairs), batch)

        if self.mode in (ProviderMode.FAST_FLIGHTS, ProviderMode.AUTO):
            primary_pairs = [(o, d) for o in origins[:2] for d in destinations[:2] if o != d]
            pair_results = []
            option_count = 0
            for orig, dest in primary_pairs:
                result = self._search_pair(LegSearch.single(orig, dest, departure_date, cabin))
                pair_results.append(result)
                option_count += len(result.options)
                if option_count >= 4 or self._has_budget_issue(result):
                    break
            if not option_count and not any(self._has_budget_issue(result) for result in pair_results):
                for orig, dest in pairs:
                    if (orig, dest) in primary_pairs:
                        continue
                    result = self._search_pair(LegSearch.single(orig, dest, departure_date, cabin))
                    pair_results.append(result)
                    if self._has_budget_issue(result):
                        break
            return self._combine_pairs(query, pair_results, len(pairs))

        raise ValueError(f"Unsupported flight provider mode: {self.mode}")

    def _search_pair(self, query: LegSearch) -> SearchResult:
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
            return SearchResult(options=serp.options, issues=issues)
        status = SearchStatus.PARTIAL if fast.status != SearchStatus.FAILED else serp.status
        return SearchResult(options=serp.options, status=status, issues=issues)

    def _search_fast_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        self._throttle(default_delay=1.0)
        self.api_calls_this_run += 1
        if self.cache is not None:
            self.cache.record_provider_call("fast_flights")
            self.cache.active_provider = "fast_flights"

        def _build_query(layover_limit: int | None) -> Any:
            return create_query(
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

        default_cap_hours = StopsPolicy().max_layover_hours
        effective_hours = max(self.max_layover_hours, default_cap_hours)
        layover_mins = round(effective_hours * 60.0) if effective_hours > 0 else None
        result_list: list[Any] = get_flights(_build_query(layover_mins))

        # If strict layover cap yielded no flights on this corridor, retry without the layover cap
        if not result_list and layover_mins is not None:
            if not self._can_make_live_call():
                raise _LiveQueryBudgetExceeded
            self._throttle(default_delay=1.0)
            self.api_calls_this_run += 1
            if self.cache is not None:
                self.cache.record_provider_call("fast_flights")
            result_list = get_flights(_build_query(None))

        return self.parse_fast_flights_results(
            results=result_list,
            origin=origin.upper(),
            destination=destination.upper(),
            departure_date=departure_date,
            cabin=cabin,
        )

    @staticmethod
    def _compute_fast_flights_layovers(raw_flights: list[Any]) -> list[float]:
        """Compute individual layover durations (hours) between consecutive fast_flights segments
        using their local arrival and departure `(date, time)` tuples.
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
        """Preserve top options across each stops bucket (nonstop, 1-stop, 2+-stop) before capping,
        prioritizing normal connections and ranking by generalized cost (base fare + layover time).
        """
        default_cap = StopsPolicy().max_layover_hours

        def rank_key(opt: FlightLegOption) -> tuple[bool, float, float]:
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
        """Convert fast_flights `Flights` objects into normalized `FlightLegOption` instances."""
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
            data = resp.json()

        if not isinstance(data, dict):
            raise _ProviderResponseError("invalid response")
        if data.get("error"):
            raise _ProviderResponseError("provider returned an error response")

        return self.parse_google_flights_payload(
            data=data,
            origin=origin.upper(),
            destination=destination.upper(),
            departure_date=departure_date,
            cabin=cabin,
        )

    @staticmethod
    def parse_google_flights_payload(
        data: dict[str, Any],
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Parse actual Google Flights JSON itineraries into normalized FlightLegOption objects.
        Extracts real segments, layover hubs, durations, flight numbers, and fares directly
        from the response payload without relying on synthetic hub or region tables.
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
