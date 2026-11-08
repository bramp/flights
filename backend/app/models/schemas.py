"""Domain models and API schemas for multi-city flight optimization."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.app.data.airports import get_airport


class CabinClass(StrEnum):
    AUTO = "auto"
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class ConcreteCabinClass(StrEnum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class StopsMode(StrEnum):
    AUTO = "auto"
    NONSTOP = "nonstop"
    ONE_STOP = "one_stop"
    ANY = "any"


class ConcreteStopsMode(StrEnum):
    NONSTOP = "nonstop"
    ONE_STOP = "one_stop"
    ANY = "any"


class TicketType(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"
    OPEN_JAW = "open_jaw"
    MULTI_CITY = "multi_city"


class StrategyKind(StrEnum):
    SINGLE_TICKET = "single_ticket"
    ALL_ONE_WAYS = "all_one_ways"
    OPEN_JAW_PLUS_REGIONAL = "open_jaw_plus_regional"
    NESTED_ROUND_TRIPS = "nested_round_trips"
    HUB_SPLIT = "hub_split"


class ProviderMode(StrEnum):
    AUTO = "auto"
    FAST_FLIGHTS = "fast_flights"
    SERPAPI = "serpapi"
    OFFLINE = "offline"


class BaggageConfig(BaseModel):
    include_carry_on: bool = True
    checked_bags: int = Field(default=0, ge=0, le=3)


class CabinPolicy(BaseModel):
    default_cabin: ConcreteCabinClass = ConcreteCabinClass.ECONOMY
    long_haul_cabin: ConcreteCabinClass = ConcreteCabinClass.BUSINESS
    long_haul_threshold_hours: float = Field(
        default=6.5,
        ge=1.0,
        le=24.0,
        description="Flights at or above this duration use long_haul_cabin when a leg is set to 'auto'.",
    )


class StopsPolicy(BaseModel):
    short_haul_stops: ConcreteStopsMode = ConcreteStopsMode.NONSTOP
    long_haul_stops: ConcreteStopsMode = ConcreteStopsMode.ONE_STOP
    nonstop_threshold_hours: float = Field(
        default=4.5,
        ge=0.5,
        le=24.0,
        description="Flights under this estimated nonstop duration use short_haul_stops when a leg is set to 'auto'.",
    )
    max_layover_hours: float = Field(
        default=6.0,
        ge=1.0,
        le=24.0,
        description="Maximum allowed layover duration (hours) per connection before falling back.",
    )


class OptimizationWeights(BaseModel):
    value_of_time_per_hour: float = Field(
        default=35.0,
        ge=0.0,
        le=500.0,
        description="Dollar penalty per hour of total travel time.",
    )
    protected_transfer_penalty: float = Field(
        default=45.0,
        ge=0.0,
        le=1000.0,
        description="Dollar penalty per protected airline connection.",
    )
    self_transfer_penalty: float = Field(
        default=140.0,
        ge=0.0,
        le=1500.0,
        description="Dollar penalty per unprotected self-transfer (separate tickets at a hub).",
    )
    separate_ticket_penalty: float = Field(
        default=20.0,
        ge=0.0,
        le=500.0,
        description="Small administrative friction penalty per additional ticket booked.",
    )
    enable_hub_splitting: bool = Field(
        default=True,
        description="Whether to test splitting legs at intermediate hubs.",
    )


class CityStopSpec(BaseModel):
    id: str = Field(description="Unique identifier for the stop in the UI.")
    label: str = Field(description="City or region display name (e.g. London, Tokyo).")
    airports: list[str] = Field(
        min_length=1,
        description="Allowed IATA airport codes for this stop (e.g. ['LHR', 'LGW']).",
    )
    earliest_arrival: date | None = None
    latest_departure: date | None = None
    min_nights: int = Field(default=3, ge=1, le=60)
    max_nights: int = Field(default=5, ge=1, le=60)
    fixed_order: bool = Field(
        default=False,
        description="If True, keeps this stop anchored in its relative position.",
    )
    outbound_cabin: CabinClass = Field(
        default=CabinClass.AUTO,
        description="Cabin preference for the flight arriving into or departing from this stop.",
    )
    outbound_stops: StopsMode = Field(
        default=StopsMode.AUTO,
        description="Maximum stops preference for the flight arriving into this stop.",
    )

    @model_validator(mode="after")
    def validate_nights_and_airports(self) -> CityStopSpec:
        self.airports = [code.strip().upper() for code in self.airports if code.strip()]
        if not self.airports:
            raise ValueError("At least one airport code must be provided for each stop.")
        self.max_nights = max(self.max_nights, self.min_nights)
        return self


class TripRequest(BaseModel):
    origin_label: str = "San Francisco"
    origin_airports: list[str] = Field(default_factory=lambda: ["SFO", "OAK", "SJC"])
    destination_label: str = "San Francisco"
    destination_airports: list[str] = Field(default_factory=lambda: ["SFO", "OAK", "SJC"])
    earliest_departure: date
    latest_departure: date | None = None
    earliest_return: date | None = None
    latest_return: date
    return_leg_cabin: CabinClass = CabinClass.AUTO
    return_leg_stops: StopsMode = StopsMode.AUTO
    ordering_mode: Literal["flexible", "fixed", "auto_tsp"] = "flexible"
    stops: list[CityStopSpec] = Field(min_length=1, max_length=8)
    baggage: BaggageConfig = Field(default_factory=BaggageConfig)
    cabin_policy: CabinPolicy = Field(default_factory=CabinPolicy)
    stops_policy: StopsPolicy = Field(default_factory=StopsPolicy)
    weights: OptimizationWeights = Field(default_factory=OptimizationWeights)
    provider_mode: ProviderMode = ProviderMode.AUTO
    max_api_calls_per_run: int = Field(
        default=25,
        ge=1,
        le=250,
        description="Hard cap on external live flight queries made during a single optimization run.",
    )
    force_refresh: bool = False

    @model_validator(mode="after")
    def validate_trip_dates(self) -> TripRequest:
        self.origin_airports = [c.strip().upper() for c in self.origin_airports if c.strip()]
        self.destination_airports = [c.strip().upper() for c in self.destination_airports if c.strip()]
        if not self.origin_airports:
            raise ValueError("At least one origin airport code is required.")
        if not self.destination_airports:
            raise ValueError("At least one destination airport code is required.")
        if self.latest_return <= self.earliest_departure:
            raise ValueError("latest_return must be after earliest_departure")
        return self


def parse_hm_hours(hm: str) -> float | None:
    """Parse a 24-hour 'HH:MM' string into fractional hours since midnight using stdlib `datetime.time`."""
    try:
        parsed = time.fromisoformat(hm.strip()[:5])
        return parsed.hour + parsed.minute / 60.0
    except ValueError:
        return None


def parse_local_datetime(
    raw: Any,
    fallback_date: date,
    fallback_hm: str = "09:00",
) -> tuple[date, str, datetime | None]:
    """Parse an airport-local date and 24h 'HH:MM' time from a `fast_flights` `SimpleDatetime`,
    an ISO / SerpApi `'YYYY-MM-DD HH:MM'` string, or a `'HH:MM'` string.
    """
    if raw is not None:
        d_tuple = getattr(raw, "date", None)
        t_tuple = getattr(raw, "time", None)
        if isinstance(d_tuple, (tuple, list)) and len(d_tuple) == 3 and all(isinstance(x, int) for x in d_tuple):
            hh = int(t_tuple[0] or 0) if isinstance(t_tuple, (tuple, list)) and len(t_tuple) >= 1 else 0
            mm = int(t_tuple[1] or 0) if isinstance(t_tuple, (tuple, list)) and len(t_tuple) >= 2 else 0
            try:
                dt = datetime(int(d_tuple[0]), int(d_tuple[1]), int(d_tuple[2]), hh, mm, tzinfo=UTC)
                return dt.date(), dt.strftime("%H:%M"), dt
            except ValueError:
                pass
        if isinstance(t_tuple, (tuple, list)) and len(t_tuple) >= 2:
            hh = int(t_tuple[0] or 0)
            mm = int(t_tuple[1] or 0)
            hm = f"{hh:02d}:{mm:02d}"
            return fallback_date, hm, None

    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        try:
            dt = datetime.fromisoformat(text)
            return dt.date(), dt.strftime("%H:%M"), dt.replace(tzinfo=UTC)
        except ValueError:
            pass
        try:
            t_val = time.fromisoformat(text[:5])
            return fallback_date, t_val.strftime("%H:%M"), None
        except ValueError:
            pass

    return fallback_date, fallback_hm, None


def offset_date_and_hm(base_date: date, total_hours_from_midnight: float, minute: int) -> tuple[date, str]:
    """Return `(local_date, 'HH:MM')` given fractional hours elapsed since `base_date` 00:00."""
    day_offset = int(total_hours_from_midnight // 24)
    hour_of_day = int(total_hours_from_midnight % 24)
    return base_date + timedelta(days=day_offset), f"{hour_of_day:02d}:{minute:02d}"


class FlightSegment(BaseModel):
    origin: str
    destination: str
    departure_date: date
    departure_time: str = "09:30"
    arrival_date: date | None = None
    arrival_time: str = "17:45"
    airline: str
    airline_name: str
    alliance: str
    flight_number: str
    duration_hours: float
    cabin: ConcreteCabinClass
    aircraft: str = "B787-9"


class FlightLegOption(BaseModel):
    """A single directional flight journey between two airports on a given date."""

    leg_id: str
    origin: str
    destination: str
    departure_date: date
    departure_time: str = ""
    arrival_date: date | None = None
    arrival_time: str = ""
    arrival_day_offset: int = 0
    cabin: ConcreteCabinClass
    airline: str
    airline_name: str
    alliance: str
    flight_numbers: list[str]
    segments: list[FlightSegment]
    duration_hours: float
    stops_count: int
    layover_airports: list[str] = Field(default_factory=list)
    layover_hours: float = 0.0
    one_way_base_fare_usd: float
    round_trip_half_fare_usd: float
    bag_fee_per_checked_bag_usd: float
    includes_carry_on: bool = True
    is_lcc: bool = False
    provider: str = "pricing_engine"
    from_cache: bool = False

    @model_validator(mode="after")
    def populate_segment_and_leg_times(self) -> FlightLegOption:
        for idx, seg in enumerate(self.segments):
            if seg.arrival_date is not None:
                continue
            if idx + 1 < len(self.segments):
                next_seg = self.segments[idx + 1]
                arr_hm = parse_hm_hours(seg.arrival_time)
                next_dep_hm = parse_hm_hours(next_seg.departure_time)
                if arr_hm is not None and next_dep_hm is not None:
                    per_stop_layover = self.layover_hours / max(1, self.stops_count)
                    layover_days = max(0, round((per_stop_layover - (next_dep_hm - arr_hm)) / 24.0))
                    seg.arrival_date = max(seg.departure_date, next_seg.departure_date - timedelta(days=layover_days))
                else:
                    seg.arrival_date = seg.departure_date
            else:
                dep_hm = parse_hm_hours(seg.departure_time)
                arr_hm = parse_hm_hours(seg.arrival_time)
                if dep_hm is not None and arr_hm is not None:
                    orig_info = get_airport(seg.origin)
                    dest_info = get_airport(seg.destination)
                    if self.provider != "pricing_engine" and orig_info.has_coordinates and dest_info.has_coordinates:
                        tz_diff = (dest_info.lon - orig_info.lon) / 15.0
                        day_delta = round((dep_hm + seg.duration_hours + tz_diff - arr_hm) / 24.0)
                    else:
                        day_delta = 1 if arr_hm < dep_hm else int((dep_hm + seg.duration_hours) // 24)
                    seg.arrival_date = seg.departure_date + timedelta(days=day_delta)
                else:
                    seg.arrival_date = seg.departure_date

        if self.segments:
            first_seg = self.segments[0]
            last_seg = self.segments[-1]
            if not self.departure_time:
                self.departure_time = first_seg.departure_time
            if self.arrival_date is None:
                self.arrival_date = last_seg.arrival_date or self.departure_date
            if not self.arrival_time:
                self.arrival_time = last_seg.arrival_time
            self.arrival_day_offset = (self.arrival_date - self.departure_date).days
        return self


class FareProvenance(StrEnum):
    ESTIMATED = "estimated"
    VERIFIED = "verified"


class FareEstimate(BaseModel):
    amount_usd: float
    provenance: FareProvenance = FareProvenance.ESTIMATED
    assumptions: list[str] = Field(default_factory=list)


class BookedTicket(BaseModel):
    """A proposed ticket covering one or more legs in chronological order."""

    ticket_id: str
    ticket_type: TicketType
    label: str
    airline_or_alliance: str
    cabin_summary: str
    legs: list[FlightLegOption]
    leg_indices: list[int] = Field(description="0-based indices of the trip legs covered by this ticket.")
    fare_estimate: FareEstimate
    baggage_fees_usd: float
    total_ticket_usd: float
    pricing_note: str
    booking_query_summary: str
    google_flights_url: str = ""


class ScheduledStopVisit(BaseModel):
    stop_id: str
    label: str
    arrival_airport: str
    departure_airport: str
    arrival_date: date
    departure_date: date
    nights: int


class EvaluatedItinerary(BaseModel):
    itinerary_id: str
    strategy: StrategyKind
    strategy_label: str
    strategy_description: str
    badges: list[str] = Field(default_factory=list)
    route_summary: str
    stop_visits: list[ScheduledStopVisit]
    legs: list[FlightLegOption]
    tickets: list[BookedTicket]
    total_base_fare_usd: float
    total_baggage_fees_usd: float
    total_price_usd: float
    total_travel_hours: float
    total_flight_hours: float
    total_layover_hours: float
    protected_transfers: int
    self_transfers: int
    self_transfer_hubs: list[str] = Field(default_factory=list)
    min_self_transfer_buffer_hours: float | None = None
    effective_score: float
    savings_vs_single_ticket_usd: float = 0.0
    savings_vs_all_one_ways_usd: float = 0.0
    explanation_bullets: list[str] = Field(default_factory=list)


class CacheStats(BaseModel):
    cache_hits: int = 0
    cache_misses: int = 0
    total_cached_flights_in_db: int = 0
    serpapi_calls_this_run: int = 0
    fast_flights_calls_this_run: int = 0
    total_serpapi_calls_logged: int = 0
    active_provider: str = "auto"


class OptimizationResponse(BaseModel):
    api_version: Literal[2] = 2
    recommended: EvaluatedItinerary
    pareto_frontier: list[EvaluatedItinerary]
    strategy_comparison: list[EvaluatedItinerary]
    schedules_evaluated: int
    ticket_partitions_evaluated: int
    cache_stats: CacheStats
    warnings: list[str] = Field(default_factory=list)
