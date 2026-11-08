"""Domain models and API schemas for multi-city flight optimization."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.app.data.airports import get_airport


class CabinClass(StrEnum):
    """Select a cabin class or defer to the duration-based cabin policy."""

    AUTO = "auto"
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class ConcreteCabinClass(StrEnum):
    """Represent a cabin class after any automatic selection is resolved.

    Examples:
        >>> from backend.app.models.schemas import ConcreteCabinClass
        >>> ConcreteCabinClass("business").value
        'business'
    """

    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class StopsMode(StrEnum):
    """Select a connection limit or defer to the automatic stops policy.

    ``ONE_STOP`` permits at most one connection, including nonstop flights.
    """

    AUTO = "auto"
    NONSTOP = "nonstop"
    ONE_STOP = "one_stop"
    ANY = "any"


class ConcreteStopsMode(StrEnum):
    """Represent a connection limit without an automatic option."""

    NONSTOP = "nonstop"
    ONE_STOP = "one_stop"
    ANY = "any"


class TicketType(StrEnum):
    """Classify a proposed ticket by the legs it covers.

    Attributes:
        ONE_WAY: One leg from origin to destination, possibly with connections,
            such as SFO -> LHR.
        ROUND_TRIP: An outbound and return leg between the same airports,
            such as SFO -> LHR and LHR -> SFO.
        OPEN_JAW: An outbound and return leg that do not exactly reverse each
            other. For example, SFO -> LHR and CDG -> SFO return from a
            different airport, while SFO -> LHR and LHR -> LAX return to a
            different airport. Any travel across the gap must be arranged
            separately.
        MULTI_CITY: Multiple legs booked on one ticket, such as SFO -> LHR,
            LHR -> CDG, and CDG -> SFO.
    """

    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"
    OPEN_JAW = "open_jaw"
    MULTI_CITY = "multi_city"


class StrategyKind(StrEnum):
    """Identify a strategy for dividing an itinerary into tickets.

    Attributes:
        SINGLE_TICKET: Cover all legs with one ticket.
        ALL_ONE_WAYS: Book each leg separately.
        OPEN_JAW_PLUS_REGIONAL: Combine an outer ticket with regional one-ways.
        NESTED_ROUND_TRIPS: Use separate outer and inner tickets.
        HUB_SPLIT: Split a leg at an intermediate hub using separate tickets.
    """

    SINGLE_TICKET = "single_ticket"
    ALL_ONE_WAYS = "all_one_ways"
    OPEN_JAW_PLUS_REGIONAL = "open_jaw_plus_regional"
    NESTED_ROUND_TRIPS = "nested_round_trips"
    HUB_SPLIT = "hub_split"


class ProviderMode(StrEnum):
    """Select the source of candidate flights.

    Attributes:
        AUTO: Try fast-flights first and fall back to SerpApi when needed and available.
        FAST_FLIGHTS: Use the fast-flights provider.
        SERPAPI: Use SerpApi, which requires credentials.
        OFFLINE: Use simulated flights; available only in testing mode.
    """

    AUTO = "auto"
    FAST_FLIGHTS = "fast_flights"
    SERPAPI = "serpapi"
    OFFLINE = "offline"


class BaggageConfig(BaseModel):
    """Set the baggage requirements used for pricing and booking links.

    Examples:
        >>> from backend.app.models.schemas import BaggageConfig
        >>> BaggageConfig(checked_bags=1).model_dump()
        {'include_carry_on': True, 'checked_bags': 1}
    """

    include_carry_on: bool = Field(default=True, description="Whether to include a carry-on bag.")
    checked_bags: int = Field(
        default=0,
        ge=0,
        le=3,
        description="Number of checked bags to include, from 0 to 3.",
    )


class CabinPolicy(BaseModel):
    """Choose cabins for legs whose cabin preference is automatic.

    Examples:
        >>> from backend.app.models.schemas import CabinPolicy
        >>> CabinPolicy(long_haul_threshold_hours=7).long_haul_cabin.value
        'business'
    """

    default_cabin: ConcreteCabinClass = Field(
        default=ConcreteCabinClass.ECONOMY,
        description="Cabin used below the long-haul duration threshold.",
    )
    long_haul_cabin: ConcreteCabinClass = Field(
        default=ConcreteCabinClass.BUSINESS,
        description="Cabin used at or above the long-haul duration threshold.",
    )
    long_haul_threshold_hours: float = Field(
        default=6.5,
        ge=1.0,
        le=24.0,
        description="Estimated nonstop duration in hours at which automatic cabin selection uses long_haul_cabin.",
    )


class StopsPolicy(BaseModel):
    """Choose connection limits for automatic preferences.

    The solver can relax a stops or layover limit when no candidate meets it.

    Examples:
        >>> from backend.app.models.schemas import ConcreteStopsMode, StopsPolicy
        >>> StopsPolicy(short_haul_stops=ConcreteStopsMode.ONE_STOP).short_haul_stops.value
        'one_stop'
    """

    short_haul_stops: ConcreteStopsMode = Field(
        default=ConcreteStopsMode.NONSTOP,
        description="Connection limit below the nonstop duration threshold.",
    )
    long_haul_stops: ConcreteStopsMode = Field(
        default=ConcreteStopsMode.ONE_STOP,
        description="Connection limit at or above the nonstop duration threshold.",
    )
    nonstop_threshold_hours: float = Field(
        default=4.5,
        ge=0.5,
        le=24.0,
        description="Nonstop duration threshold in hours below which automatic selection uses short_haul_stops.",
    )
    max_layover_hours: float = Field(
        default=6.0,
        ge=1.0,
        le=24.0,
        description="Preferred maximum average layover hours per connection; the solver may relax this limit.",
    )


class OptimizationWeights(BaseModel):
    """Set USD-valued penalties used to compare itinerary scores.

    Examples:
        >>> from backend.app.models.schemas import OptimizationWeights
        >>> OptimizationWeights(value_of_time_per_hour=50).value_of_time_per_hour
        50.0
    """

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
    """Describe a city stay and preferences for the flight arriving there.

    Airport codes are stripped and uppercased, and blank codes are removed.
    Duplicate codes are retained, and this model does not check the airport
    registry. If the maximum stay is below the minimum, it is raised to the
    minimum.

    Examples:
        >>> from backend.app.models.schemas import CityStopSpec
        >>> stop = CityStopSpec(id="lon", label="London", airports=[" lhr ", "lgw"], min_nights=5, max_nights=3)
        >>> stop.airports, stop.max_nights
        (['LHR', 'LGW'], 5)
    """

    id: str = Field(description="Unique identifier for the stop in the UI.")
    label: str = Field(description="City or region display name (e.g. London, Tokyo).")
    airports: list[str] = Field(
        min_length=1,
        description="Allowed IATA airport codes for this stop (e.g. ['LHR', 'LGW']).",
    )
    earliest_arrival: date | None = Field(
        default=None,
        description="Earliest preferred planned arrival date, inclusive; the scheduler uses the inbound leg's departure date.",
    )
    latest_departure: date | None = Field(default=None, description="Latest preferred departure date, inclusive.")
    min_nights: int = Field(default=3, ge=1, le=60, description="Minimum preferred stay, in nights.")
    max_nights: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Maximum preferred stay, in nights; raised to min_nights if smaller.",
    )
    fixed_order: bool = Field(
        default=False,
        description="Keep this stop at its input position when the ordering mode is flexible.",
    )
    outbound_cabin: CabinClass = Field(
        default=CabinClass.AUTO,
        description="Cabin preference for the flight arriving at this stop.",
    )
    outbound_stops: StopsMode = Field(
        default=StopsMode.AUTO,
        description="Connection limit for the flight arriving at this stop.",
    )

    @model_validator(mode="after")
    def validate_nights_and_airports(self) -> CityStopSpec:
        """Normalize airport codes and ensure the maximum stay is at least the minimum.

        Raises:
            ValueError: If no nonblank airport code remains.
        """
        self.airports = [code.strip().upper() for code in self.airports if code.strip()]
        if not self.airports:
            raise ValueError("At least one airport code must be provided for each stop.")
        self.max_nights = max(self.max_nights, self.min_nights)
        return self


class TripRequest(BaseModel):
    """Define a trip window, city stops, and optimization preferences.

    Origin and destination codes are stripped and uppercased, and blank codes
    are removed. Each list must retain at least one code. Duplicates are
    retained, and this model does not check the airport registry. The date
    validator checks that the latest return is after the earliest departure;
    it does not check the other date relationships. The scheduler can relax
    preferences when it cannot find a matching schedule.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.schemas import CityStopSpec, TripRequest
        >>> trip = TripRequest(
        ...     origin_airports=["SFO"],
        ...     destination_airports=["SFO"],
        ...     earliest_departure=date(2026, 11, 10),
        ...     latest_return=date(2026, 11, 17),
        ...     stops=[CityStopSpec(id="lon", label="London", airports=["LHR"])],
        ... )
        >>> trip.stops[0].label
        'London'
    """

    origin_label: str = Field(default="San Francisco", description="Display name for the trip origin.")
    origin_airports: list[str] = Field(
        default_factory=lambda: ["SFO", "OAK", "SJC"],
        description="Allowed origin airport codes, in priority order.",
    )
    destination_label: str = Field(default="San Francisco", description="Display name for the final destination.")
    destination_airports: list[str] = Field(
        default_factory=lambda: ["SFO", "OAK", "SJC"],
        description="Allowed final destination airport codes, in priority order.",
    )
    earliest_departure: date = Field(description="Earliest trip departure date, inclusive.")
    latest_departure: date | None = Field(default=None, description="Latest preferred trip departure date, inclusive.")
    earliest_return: date | None = Field(
        default=None,
        description="Earliest preferred departure date for the final leg, inclusive.",
    )
    latest_return: date = Field(description="Latest preferred departure date for the final leg, inclusive.")
    return_leg_cabin: CabinClass = Field(
        default=CabinClass.AUTO,
        description="Cabin preference for the final flight to the destination.",
    )
    return_leg_stops: StopsMode = Field(
        default=StopsMode.AUTO,
        description="Connection limit for the final flight to the destination.",
    )
    ordering_mode: Literal["flexible", "fixed", "auto_tsp"] = Field(
        default="flexible",
        description="Stop ordering: flexible respects pins, fixed follows input order, and auto_tsp may reorder all.",
    )
    stops: list[CityStopSpec] = Field(min_length=1, max_length=8, description="City stops to visit, from 1 to 8.")
    baggage: BaggageConfig = Field(default_factory=BaggageConfig, description="Trip-wide baggage requirements.")
    cabin_policy: CabinPolicy = Field(default_factory=CabinPolicy, description="Rules for automatic cabin selection.")
    stops_policy: StopsPolicy = Field(default_factory=StopsPolicy, description="Rules for automatic connection limits.")
    weights: OptimizationWeights = Field(default_factory=OptimizationWeights, description="Itinerary scoring weights.")
    provider_mode: ProviderMode = Field(default=ProviderMode.AUTO, description="Source of candidate flights.")
    max_api_calls_per_run: int = Field(
        default=25,
        ge=1,
        le=250,
        description="Hard cap on external live flight queries made during a single optimization run.",
    )
    force_refresh: bool = Field(
        default=False,
        description="Skip persistent flight-cache reads for this run; searches may still be reused within the run.",
    )

    @model_validator(mode="after")
    def validate_trip_dates(self) -> TripRequest:
        """Normalize endpoint codes and check the trip's outer date bounds.

        Raises:
            ValueError: If either airport list is empty after normalization or
                the latest return is not after the earliest departure.
        """
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
    """Return fractional hours since midnight for a time string.

    Strip whitespace and parse only the first five characters. Return ``None``
    if those characters are not a valid ISO time.

    Examples:
        >>> from backend.app.models.schemas import parse_hm_hours
        >>> parse_hm_hours("09:30")
        9.5
        >>> parse_hm_hours("not-a-time") is None
        True
    """
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
    """Parse a provider wall time into a date, time text, and optional datetime.

    Accept an ISO date or datetime string, a time string, or an object with
    date and time tuple or list attributes. When a full date is parsed, the
    returned datetime is tagged as UTC without converting the wall time or
    preserving an input offset. It is not necessarily a UTC instant.

    Time-only input uses ``fallback_date`` and returns no datetime. An
    unrecognized value also uses ``fallback_hm``. Truthy components of a
    supplied time tuple are converted with ``int`` and may raise errors.

    Args:
        raw: Provider value to parse.
        fallback_date: Date used when the input has no usable date.
        fallback_hm: Time text returned when no supported time is found.

    Returns:
        The date, time text (normally ``HH:MM``), and UTC-tagged datetime
        or ``None``.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.schemas import parse_local_datetime
        >>> day, hm, marked = parse_local_datetime("2026-11-10T09:30:00+02:00", date(2026, 1, 1))
        >>> day.isoformat(), hm, marked.isoformat() if marked else None
        ('2026-11-10', '09:30', '2026-11-10T09:30:00+00:00')
        >>> day, hm, marked = parse_local_datetime("09:30", date(2026, 11, 10))
        >>> day.isoformat(), hm, marked is None
        ('2026-11-10', '09:30', True)
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
    """Return a local date and time for an hour offset from midnight.

    The minute comes from ``minute``, not from the fractional part of the
    offset. The minute is formatted without a range check.

    Args:
        base_date: Local date whose midnight starts the offset.
        total_hours_from_midnight: Hours from that midnight.
        minute: Minute to include in the time text.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.schemas import offset_date_and_hm
        >>> day, hm = offset_date_and_hm(date(2026, 11, 10), 26.25, 15)
        >>> day.isoformat(), hm
        ('2026-11-11', '02:15')
    """
    day_offset = int(total_hours_from_midnight // 24)
    hour_of_day = int(total_hours_from_midnight % 24)
    return base_date + timedelta(days=day_offset), f"{hour_of_day:02d}:{minute:02d}"


class FlightSegment(BaseModel):
    """Describe one flight from takeoff to landing.

    Dates and times are local to their respective airports.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.schemas import ConcreteCabinClass, FlightSegment
        >>> segment = FlightSegment(
        ...     origin="SFO",
        ...     destination="LHR",
        ...     departure_date=date(2026, 11, 10),
        ...     departure_time="19:30",
        ...     arrival_date=date(2026, 11, 11),
        ...     arrival_time="14:00",
        ...     airline="XX",
        ...     airline_name="Example Air",
        ...     alliance="None",
        ...     flight_number="XX100",
        ...     duration_hours=10.5,
        ...     cabin=ConcreteCabinClass.ECONOMY,
        ... )
        >>> segment.arrival_date.isoformat()
        '2026-11-11'
    """

    origin: str = Field(description="Departure airport code.")
    destination: str = Field(description="Arrival airport code.")
    departure_date: date = Field(description="Departure date at the origin airport.")
    departure_time: str = Field(default="09:30", description="Local departure time, normally HH:MM.")
    arrival_date: date | None = Field(default=None, description="Arrival date at the destination airport, if known.")
    arrival_time: str = Field(default="17:45", description="Local arrival time, normally HH:MM.")
    airline: str = Field(description="Airline code or identifier.")
    airline_name: str = Field(description="Display name of the airline.")
    alliance: str = Field(description="Airline alliance label.")
    flight_number: str = Field(description="Flight number for this segment.")
    duration_hours: float = Field(description="Flight duration in hours, excluding layovers.")
    cabin: ConcreteCabinClass = Field(description="Cabin class for the segment.")
    aircraft: str = Field(default="B787-9", description="Aircraft type or provider-supplied label.")


class FlightLegOption(BaseModel):
    """Describe a candidate journey between two airports on one departure date.

    A leg can contain multiple flight segments. When segments are present,
    validation estimates missing segment arrival dates, fills blank leg times,
    and recomputes the arrival day offset. These estimates update the segment
    models and may not reflect actual time-zone rules.
    """

    leg_id: str = Field(description="Identifier for this candidate leg.")
    origin: str = Field(description="Departure airport code for the leg.")
    destination: str = Field(description="Arrival airport code for the leg.")
    departure_date: date = Field(description="Departure date at the origin airport.")
    departure_time: str = Field(default="", description="Local departure time, normally HH:MM.")
    arrival_date: date | None = Field(default=None, description="Local arrival date, if known or inferred.")
    arrival_time: str = Field(default="", description="Local arrival time, normally HH:MM.")
    arrival_day_offset: int = Field(default=0, description="Calendar days between departure and arrival.")
    cabin: ConcreteCabinClass = Field(description="Cabin class requested for the leg.")
    airline: str = Field(description="Airline code or identifier for the leg.")
    airline_name: str = Field(description="Display name of the airline.")
    alliance: str = Field(description="Airline alliance label.")
    flight_numbers: list[str] = Field(description="Flight numbers for the leg's segments.")
    segments: list[FlightSegment] = Field(description="Flight segments in travel order.")
    duration_hours: float = Field(description="Total leg duration in hours, including layovers.")
    stops_count: int = Field(description="Number of connections in the leg.")
    layover_airports: list[str] = Field(default_factory=list, description="Airport codes for connections.")
    layover_hours: float = Field(default=0.0, description="Total layover time across the leg, in hours.")
    one_way_base_fare_usd: float = Field(description="Candidate one-way base fare in USD.")
    round_trip_half_fare_usd: float = Field(description="Estimated half of a round-trip fare in USD.")
    bag_fee_per_checked_bag_usd: float = Field(description="Estimated fee per checked bag in USD.")
    includes_carry_on: bool = Field(default=True, description="Whether the candidate fare includes a carry-on.")
    is_lcc: bool = Field(default=False, description="Whether the leg uses a low-cost carrier.")
    provider: str = Field(default="pricing_engine", description="Provider that supplied the flight option.")
    from_cache: bool = Field(default=False, description="Whether the flight option was served from the cache.")

    @model_validator(mode="after")
    def populate_segment_and_leg_times(self) -> FlightLegOption:
        """Fill missing segment dates and derive leg times from the segments.

        This updates the segment models and the leg. When segments are present,
        the arrival day offset is recomputed even if a value was supplied.
        """
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
    """Identify whether a fare is estimated or reported as verified.

    The model does not itself verify a fare.
    """

    ESTIMATED = "estimated"
    VERIFIED = "verified"


class FareEstimate(BaseModel):
    """Describe a ticket base fare and the assumptions behind it.

    Examples:
        >>> from backend.app.models.schemas import FareEstimate
        >>> fare = FareEstimate(amount_usd=450.0, assumptions=["Based on one-way candidates."])
        >>> fare.provenance.value
        'estimated'
    """

    amount_usd: float = Field(description="Ticket base fare in USD, excluding baggage fees.")
    provenance: FareProvenance = Field(default=FareProvenance.ESTIMATED, description="Source status of the fare.")
    assumptions: list[str] = Field(default_factory=list, description="Pricing assumptions and limitations.")


class BookedTicket(BaseModel):
    """Describe a proposed ticket covering one or more legs in travel order.

    This is not a confirmed booking. All listed legs must be flown in order;
    the model does not verify the booking or ticket coverage.
    """

    ticket_id: str = Field(description="Identifier for the proposed ticket.")
    ticket_type: TicketType = Field(description="Type of ticket covering the listed legs.")
    label: str = Field(description="Display label for the ticket.")
    airline_or_alliance: str = Field(description="Airline or alliance used to describe the ticket.")
    cabin_summary: str = Field(description="Display summary of the ticket's cabin classes.")
    legs: list[FlightLegOption] = Field(description="Legs covered by the ticket, in travel order.")
    leg_indices: list[int] = Field(description="Zero-based indices of covered legs in the itinerary.")
    fare_estimate: FareEstimate = Field(description="Base fare and its provenance.")
    baggage_fees_usd: float = Field(description="Estimated baggage fees for the ticket, in USD.")
    total_ticket_usd: float = Field(description="Base fare plus baggage fees, in USD.")
    pricing_note: str = Field(description="Explanation of the ticket's pricing approach.")
    booking_query_summary: str = Field(description="Human-readable summary of the suggested booking search.")
    google_flights_url: str = Field(default="", description="Google Flights search URL, if available.")


class ScheduledStopVisit(BaseModel):
    """Describe a scheduled city stay, including its arrival and departure.

    The arrival and departure airports can differ within the same city stay.
    The scheduled arrival date may differ from the actual flight arrival date.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.schemas import ScheduledStopVisit
        >>> visit = ScheduledStopVisit(
        ...     stop_id="lon",
        ...     label="London",
        ...     arrival_airport="LHR",
        ...     departure_airport="LGW",
        ...     arrival_date=date(2026, 11, 10),
        ...     departure_date=date(2026, 11, 14),
        ...     nights=4,
        ... )
        >>> visit.arrival_airport, visit.departure_airport
        ('LHR', 'LGW')
    """

    stop_id: str = Field(description="Identifier of the requested city stop.")
    label: str = Field(description="Display name of the city stop.")
    arrival_airport: str = Field(description="Airport code where the visit begins.")
    departure_airport: str = Field(description="Airport code where the visit ends.")
    arrival_date: date = Field(description="Planned arrival date, based on the inbound planned leg's departure date.")
    departure_date: date = Field(description="Departure date for the visit.")
    nights: int = Field(description="Planned nights at the stop, calculated from the scheduled visit dates.")


class EvaluatedItinerary(BaseModel):
    """Report a proposed itinerary, its tickets, and comparison metrics.

    The effective score combines price with time, transfer, and ticket
    penalties. A lower score is better. Fares and baggage fees may be
    estimates rather than confirmed prices.
    """

    itinerary_id: str = Field(description="Identifier for this evaluated itinerary.")
    strategy: StrategyKind = Field(description="Ticket-partitioning strategy used.")
    strategy_label: str = Field(description="Display name of the strategy.")
    strategy_description: str = Field(description="Explanation of the strategy.")
    badges: list[str] = Field(default_factory=list, description="Labels highlighting comparison results.")
    route_summary: str = Field(description="Display summary of the route's airport codes.")
    stop_visits: list[ScheduledStopVisit] = Field(description="Scheduled city visits in travel order.")
    legs: list[FlightLegOption] = Field(description="Flight legs in travel order.")
    tickets: list[BookedTicket] = Field(description="Proposed tickets covering the itinerary.")
    total_base_fare_usd: float = Field(description="Sum of ticket base fares in USD.")
    total_baggage_fees_usd: float = Field(description="Sum of estimated baggage fees in USD.")
    total_price_usd: float = Field(description="Total base fare and baggage fees in USD.")
    total_travel_hours: float = Field(description="Flight and layover time in hours, excluding city stays.")
    total_flight_hours: float = Field(description="Flight time in hours, excluding layovers.")
    total_layover_hours: float = Field(description="Layover and self-transfer buffer time in hours.")
    protected_transfers: int = Field(description="Number of within-leg stops counted as protected connections.")
    self_transfers: int = Field(description="Number of connections between separate tickets.")
    self_transfer_hubs: list[str] = Field(default_factory=list, description="Airport codes for self-transfer hubs.")
    min_self_transfer_buffer_hours: float | None = Field(
        default=None,
        description="Minimum self-transfer buffer used by the strategy, in hours, if applicable.",
    )
    effective_score: float = Field(description="Generalized USD score including price and weighted penalties.")
    savings_vs_single_ticket_usd: float = Field(
        default=0.0,
        description="Single-ticket baseline price minus this price in USD; may be negative.",
    )
    savings_vs_all_one_ways_usd: float = Field(
        default=0.0,
        description="All-one-ways baseline price minus this price in USD; may be negative.",
    )
    explanation_bullets: list[str] = Field(default_factory=list, description="Explanations of the proposed itinerary.")


class CacheStats(BaseModel):
    """Report cache and provider usage counters.

    Examples:
        >>> from backend.app.models.schemas import CacheStats
        >>> CacheStats(cache_hits=3).cache_hits
        3
    """

    cache_hits: int = Field(default=0, description="Cache hits since the session counters were reset.")
    cache_misses: int = Field(default=0, description="Cache misses since the session counters were reset.")
    total_cached_flights_in_db: int = Field(default=0, description="Number of cached flight records in the database.")
    serpapi_calls_this_run: int = Field(default=0, description="SerpApi calls since the session counters were reset.")
    fast_flights_calls_this_run: int = Field(
        default=0,
        description="Fast-flights calls since the session counters were reset.",
    )
    total_serpapi_calls_logged: int = Field(default=0, description="SerpApi calls recorded in the database.")
    active_provider: str = Field(default="auto", description="Active provider mode.")


class OptimizationResponse(BaseModel):
    """Return recommended and comparison itineraries from an optimization run.

    Results reflect the candidates the optimizer evaluated; they do not prove
    that every possible flight or ticket combination was searched.
    """

    api_version: Literal[2] = Field(default=2, description="Response schema version.")
    recommended: EvaluatedItinerary = Field(description="Evaluated itinerary with the lowest effective score.")
    pareto_frontier: list[EvaluatedItinerary] = Field(
        description="Up to eight non-dominated evaluated itineraries, ordered by effective score."
    )
    strategy_comparison: list[EvaluatedItinerary] = Field(
        description="Best evaluated itinerary for each available strategy, ordered by effective score."
    )
    schedules_evaluated: int = Field(description="Number of candidate schedules evaluated.")
    ticket_partitions_evaluated: int = Field(description="Number of evaluated itinerary and ticket-partition results.")
    cache_stats: CacheStats = Field(description="Cache and provider usage counters.")
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about relaxed constraints, incomplete searches, or simulated data.",
    )
