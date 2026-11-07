"""Domain models and API schemas for multi-city flight optimization."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class FlightSegment(BaseModel):
    origin: str
    destination: str
    departure_date: date
    departure_time: str = "09:30"
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


class BookedTicket(BaseModel):
    """A single bookable ticket (PNR) covering one or more legs in chronological order."""

    ticket_id: str
    ticket_type: TicketType
    label: str
    airline_or_alliance: str
    cabin_summary: str
    legs: list[FlightLegOption]
    leg_indices: list[int] = Field(description="0-based indices of the trip legs covered by this ticket.")
    base_fare_usd: float
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
    total_cached_quotes_in_db: int = 0
    serpapi_calls_this_run: int = 0
    fast_flights_calls_this_run: int = 0
    total_serpapi_calls_logged: int = 0
    active_provider: str = "auto"


class OptimizationResponse(BaseModel):
    recommended: EvaluatedItinerary
    pareto_frontier: list[EvaluatedItinerary]
    strategy_comparison: list[EvaluatedItinerary]
    schedules_evaluated: int
    ticket_partitions_evaluated: int
    cache_stats: CacheStats
    warnings: list[str] = Field(default_factory=list)
