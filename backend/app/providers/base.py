"""Abstract flight search provider and cache-backed provider decorator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption, TicketType


@dataclass(frozen=True)
class SliceQuery:
    origin: str
    destination: str
    departure_date: date
    cabin: ConcreteCabinClass


class FlightSearchProvider(ABC):
    """Protocol for fetching candidate flight options and multi-slice ticket quotes."""

    @abstractmethod
    def search_leg(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Return candidate flight leg options for (origin, destination, departure_date, cabin)."""

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

        # Round-Trip / Open-Jaw / Multi-City pricing on a shared alliance
        alliances = {leg.alliance for leg in legs}
        any_lcc = any(leg.is_lcc for leg in legs)
        if any_lcc or len(alliances) > 1:
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
    ) -> None:
        self.delegate = delegate
        self.cache = cache
        self.force_refresh = force_refresh

    def search_leg(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        if not self.force_refresh:
            cached = self.cache.get_leg_options(origin, destination, departure_date, cabin)
            if cached is not None:
                return cached
        else:
            self.cache.session_misses += 1

        fresh = self.delegate.search_leg(origin, destination, departure_date, cabin)
        self.cache.store_leg_options(origin, destination, departure_date, cabin, fresh)
        return fresh

    def quote_multi_slice_ticket(
        self,
        legs: list[FlightLegOption],
        ticket_type: TicketType,
    ) -> float:
        quote_key = f"{ticket_type.value}:" + "|".join(f"{leg.leg_id}:{leg.cabin.value}" for leg in legs)
        if not self.force_refresh:
            cached_quote = self.cache.get_ticket_quote(quote_key)
            if cached_quote is not None and "base_fare_usd" in cached_quote:
                return float(cached_quote["base_fare_usd"])

        fare = self.delegate.quote_multi_slice_ticket(legs, ticket_type)
        self.cache.store_ticket_quote(
            quote_key=quote_key,
            ticket_type=ticket_type.value,
            payload={"base_fare_usd": fare, "legs": [leg.leg_id for leg in legs]},
        )
        return fare
