"""Abstract flight search provider and cache-backed provider decorator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption, TicketType

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class SliceQuery:
    origin: str
    destination: str
    departure_date: date
    cabin: ConcreteCabinClass


class FlightSearchProvider(ABC):
    """Protocol for fetching candidate flight options and multi-slice ticket quotes."""

    def is_simulation(self) -> bool:
        return False

    @abstractmethod
    def search_leg(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Return candidate flight leg options for (origin, destination, departure_date, cabin)."""

    def search_leg_batch(
        self,
        origins: tuple[str, ...],
        destinations: tuple[str, ...],
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Search across multiple allowed origin and destination airports for a leg.
        Providers like SerpApi can override this to batch comma-separated airports into 1 query.
        """
        results: list[FlightLegOption] = []
        for orig in origins:
            for dest in destinations:
                if orig.upper() == dest.upper():
                    continue
                results.extend(self.search_leg(orig, dest, departure_date, cabin))
        return results

    def quote_multi_slice_ticket(
        self,
        legs: list[FlightLegOption],
        ticket_type: TicketType,
    ) -> float:
        """Return the combined base fare (USD) for a multi-slice ticket (RT, Open-Jaw, Multi-City).
        Providers that query live multi-city/round-trip endpoints can override this to query the
        exact combined PNR price; otherwise uses the legs' round-trip/multi-city fare components.
        """
        if not legs:
            return 0.0
        if ticket_type == TicketType.ONE_WAY or len(legs) == 1:
            return round(sum(leg.one_way_base_fare_usd for leg in legs), 2)

        # Round-Trip / Open-Jaw / Multi-City pricing on a shared alliance or the same carrier
        alliances = {leg.alliance for leg in legs}
        carriers = {leg.airline.strip().upper() for leg in legs if leg.airline.strip()}
        any_lcc = any(leg.is_lcc for leg in legs)
        shared_alliance = len(alliances) == 1 and next(iter(alliances)) in ("Star Alliance", "Oneworld", "SkyTeam")
        shared_carrier = len(carriers) == 1
        if any_lcc or not (shared_alliance or shared_carrier):
            # Non-partner carriers cannot combine onto discounted RT/OJ alliance fare buckets;
            # GDS prices them as end-on-end one-way fares or full IATA Y/J fares.
            return round(sum(leg.one_way_base_fare_usd for leg in legs), 2)

        raw_rt_sum = sum(leg.round_trip_half_fare_usd for leg in legs)
        if ticket_type in (TicketType.ROUND_TRIP, TicketType.OPEN_JAW) and len(legs) == 2:
            return round(raw_rt_sum, 2)

        # 3+ slice Multi-City on a single PNR carries a modest multi-slice combinability factor
        combinability_factor = 1.06 if len(legs) >= 3 else 1.0
        return round(raw_rt_sum * combinability_factor, 2)


class CachedFlightProvider(FlightSearchProvider):
    """Wraps a FlightSearchProvider with persistent SQLite caching for both legs and ticket quotes."""

    def __init__(
        self,
        delegate: FlightSearchProvider,
        cache: FlightCache,
        force_refresh: bool = False,
        progress_callback: ProgressCallback | None = None,
        planned_query_keys: set[str] | None = None,
    ) -> None:
        self.delegate = delegate
        self.cache = cache
        self.force_refresh = force_refresh
        self.progress_callback = progress_callback
        self.planned_query_keys: set[str] = set(planned_query_keys) if planned_query_keys else set()
        self.completed_query_keys: set[str] = set()
        self.schedule_index: int = 1
        self.schedules_total: int = 1
        self.current_schedule_route: str = ""
        self.current_strategy_label: str = ""
        self.strategies_completed: int = 0
        self.strategies_total: int = 1

    @staticmethod
    def format_query_label(
        orig_key: str,
        dest_key: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> str:
        orig_display = orig_key.replace(",", ", ")
        dest_display = dest_key.replace(",", ", ")
        cabin_display = cabin.value.replace("_", " ").title()
        return f"{orig_display} → {dest_display} ({departure_date.isoformat()} · {cabin_display})"

    def compute_progress_pct(self) -> int:
        total_q = max(1, len(self.planned_query_keys))
        done_q = min(total_q, len(self.completed_query_keys))
        q_ratio = done_q / total_q
        s_ratio = self.strategies_completed / max(1, self.strategies_total)
        pct = round((q_ratio * 0.75 + s_ratio * 0.25) * 95) + 3
        return max(3, min(99, pct))

    def emit_progress(
        self,
        phase: str,
        current_query: str,
        last_query: dict[str, Any] | None = None,
        progress_pct: int | None = None,
    ) -> None:
        if self.progress_callback is None:
            return
        total_q = max(len(self.planned_query_keys), len(self.completed_query_keys), 1)
        done_q = len(self.completed_query_keys)
        live_calls = self.cache.session_fast_flights_calls + self.cache.session_serpapi_calls
        payload: dict[str, Any] = {
            "phase": phase,
            "current_query": current_query,
            "queries_completed": done_q,
            "queries_total": total_q,
            "schedule_index": self.schedule_index,
            "schedules_total": self.schedules_total,
            "schedule_route": self.current_schedule_route,
            "strategy_label": self.current_strategy_label,
            "strategies_completed": self.strategies_completed,
            "strategies_total": self.strategies_total,
            "cache_hits": self.cache.session_hits,
            "cache_misses": self.cache.session_misses,
            "live_calls": live_calls,
            "progress_pct": progress_pct if progress_pct is not None else self.compute_progress_pct(),
        }
        if last_query is not None:
            payload["last_query"] = last_query
        self.progress_callback(payload)

    def search_leg(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        clean_orig = origin.strip().upper()
        clean_dest = destination.strip().upper()
        leg_key = self.cache.make_leg_key(clean_orig, clean_dest, departure_date, cabin)
        is_new_query = leg_key not in self.completed_query_keys
        query_label = self.format_query_label(clean_orig, clean_dest, departure_date, cabin)
        if is_new_query:
            self.planned_query_keys.add(leg_key)
            self.emit_progress(phase="query_start", current_query=query_label)

        hits_before = self.cache.session_hits
        if self.delegate.is_simulation():
            results = self.delegate.search_leg(origin, destination, departure_date, cabin)
        else:
            cached = (
                None if self.force_refresh else self.cache.get_leg_options(origin, destination, departure_date, cabin)
            )
            if cached is not None:
                results = cached
            else:
                if self.force_refresh:
                    self.cache.session_misses += 1
                results = self.delegate.search_leg(origin, destination, departure_date, cabin)
                if results:
                    self.cache.store_leg_options(origin, destination, departure_date, cabin, results)

        if is_new_query:
            self.completed_query_keys.add(leg_key)
            source = (
                "simulated"
                if self.delegate.is_simulation()
                else ("cache" if self.cache.session_hits > hits_before else "live")
            )
            self.emit_progress(
                phase="query_done",
                current_query=query_label,
                last_query={
                    "query": query_label,
                    "route": f"{clean_orig} → {clean_dest}",
                    "date": departure_date.isoformat(),
                    "cabin": cabin.value.replace("_", " ").title(),
                    "options_count": len(results),
                    "source": source,
                },
            )
        return results

    def search_leg_batch(
        self,
        origins: tuple[str, ...],
        destinations: tuple[str, ...],
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        clean_origs = tuple(dict.fromkeys(o.strip().upper() for o in origins if o.strip()))
        clean_dests = tuple(dict.fromkeys(d.strip().upper() for d in destinations if d.strip()))
        if not clean_origs or not clean_dests:
            return []

        batch_orig_key = ",".join(clean_origs)
        batch_dest_key = ",".join(clean_dests)
        leg_key = self.cache.make_leg_key(batch_orig_key, batch_dest_key, departure_date, cabin)
        is_new_query = leg_key not in self.completed_query_keys
        query_label = self.format_query_label(batch_orig_key, batch_dest_key, departure_date, cabin)
        if is_new_query:
            self.planned_query_keys.add(leg_key)
            self.emit_progress(phase="query_start", current_query=query_label)

        hits_before = self.cache.session_hits
        if self.delegate.is_simulation():
            results = self.delegate.search_leg_batch(clean_origs, clean_dests, departure_date, cabin)
        else:
            cached = (
                None
                if self.force_refresh
                else self.cache.get_leg_options(batch_orig_key, batch_dest_key, departure_date, cabin)
            )
            if cached is not None:
                results = cached
            else:
                if self.force_refresh:
                    self.cache.session_misses += 1
                results = self.delegate.search_leg_batch(clean_origs, clean_dests, departure_date, cabin)
                if results:
                    self.cache.store_leg_options(batch_orig_key, batch_dest_key, departure_date, cabin, results)

        if is_new_query:
            self.completed_query_keys.add(leg_key)
            source = (
                "simulated"
                if self.delegate.is_simulation()
                else ("cache" if self.cache.session_hits > hits_before else "live")
            )
            self.emit_progress(
                phase="query_done",
                current_query=query_label,
                last_query={
                    "query": query_label,
                    "route": f"{batch_orig_key.replace(',', ', ')} → {batch_dest_key.replace(',', ', ')}",
                    "date": departure_date.isoformat(),
                    "cabin": cabin.value.replace("_", " ").title(),
                    "options_count": len(results),
                    "source": source,
                },
            )
        return results

    def quote_multi_slice_ticket(
        self,
        legs: list[FlightLegOption],
        ticket_type: TicketType,
    ) -> float:
        if self.delegate.is_simulation() or any(leg.provider == "pricing_engine" for leg in legs):
            return self.delegate.quote_multi_slice_ticket(legs, ticket_type)
        quote_key = f"{ticket_type.value}:" + "|".join(f"{leg.leg_id}:{leg.cabin.value}" for leg in legs)
        if not self.force_refresh:
            cached_quote = self.cache.get_ticket_quote(quote_key)
            if cached_quote is not None and "base_fare_usd" in cached_quote:
                return float(cached_quote["base_fare_usd"])

        fare = self.delegate.quote_multi_slice_ticket(legs, ticket_type)
        self.cache.store_ticket_quote(
            quote_key=quote_key,
            ticket_type=ticket_type.value,
            payload={
                "base_fare_usd": fare,
                "legs": [leg.leg_id for leg in legs],
                "providers": [leg.provider for leg in legs],
            },
        )
        return fare
