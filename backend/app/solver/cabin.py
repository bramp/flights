"""Resolve per-leg cabin and connection preferences.

Cabin and stop rules use estimated flight durations when a preference is
automatic. Stop and layover limits can be relaxed when no option meets them.
"""

from __future__ import annotations

from backend.app.data.airports import estimate_nonstop_hours, get_airport
from backend.app.models.schemas import (
    CabinClass,
    CabinPolicy,
    ConcreteCabinClass,
    ConcreteStopsMode,
    FlightLegOption,
    StopsMode,
    StopsPolicy,
)

__all__ = [
    "CABIN_RANK",
    "filter_options_by_stops",
    "highest_cabin",
    "resolve_leg_cabin",
    "resolve_leg_max_stops",
]

CABIN_RANK: dict[ConcreteCabinClass, int] = {
    ConcreteCabinClass.ECONOMY: 1,
    ConcreteCabinClass.PREMIUM_ECONOMY: 2,
    ConcreteCabinClass.BUSINESS: 3,
    ConcreteCabinClass.FIRST: 4,
}


def resolve_leg_cabin(
    origin: str,
    destination: str,
    requested_cabin: CabinClass,
    policy: CabinPolicy,
) -> ConcreteCabinClass:
    """Resolve a leg's cabin from its preference and duration policy.

    An explicit preference takes precedence. For ``AUTO``, use the long-haul
    cabin when the estimated nonstop duration is at or above the policy
    threshold; otherwise use the default cabin.

    Args:
        origin: Origin airport code used for duration estimation.
        destination: Destination airport code used for duration estimation.
        requested_cabin: Explicit cabin or ``AUTO``.
        policy: Cabins and duration threshold for automatic selection.

    Returns:
        A concrete cabin class.

    Examples:
        >>> from backend.app.models.schemas import CabinClass, CabinPolicy
        >>> from backend.app.solver.cabin import resolve_leg_cabin
        >>> resolve_leg_cabin("SFO", "LHR", CabinClass.ECONOMY, CabinPolicy()).value
        'economy'
    """
    if requested_cabin != CabinClass.AUTO:
        return ConcreteCabinClass(requested_cabin.value)

    est_hours = estimate_nonstop_hours(origin, destination)
    if est_hours >= policy.long_haul_threshold_hours:
        return policy.long_haul_cabin
    return policy.default_cabin


def highest_cabin(cabins: list[ConcreteCabinClass]) -> ConcreteCabinClass:
    """Return the highest cabin, or economy when the list is empty.

    The order is economy, premium economy, business, then first. The solver
    uses this ranking when requesting a uniform cabin for a single ticket.

    Examples:
        >>> from backend.app.models.schemas import ConcreteCabinClass
        >>> from backend.app.solver.cabin import highest_cabin
        >>> highest_cabin([ConcreteCabinClass.ECONOMY, ConcreteCabinClass.BUSINESS]).value
        'business'
        >>> highest_cabin([]).value
        'economy'
    """
    if not cabins:
        return ConcreteCabinClass.ECONOMY
    return max(cabins, key=lambda c: CABIN_RANK[c])


def _stops_mode_to_limit(mode: ConcreteStopsMode) -> int | None:
    """Convert a concrete stop preference to an inclusive limit."""
    if mode == ConcreteStopsMode.NONSTOP:
        return 0
    if mode == ConcreteStopsMode.ONE_STOP:
        return 1
    return None


def resolve_leg_max_stops(
    origin: str,
    destination: str,
    requested_stops: StopsMode,
    policy: StopsPolicy,
    options: list[FlightLegOption] | None = None,
) -> int | None:
    """Resolve the preferred maximum number of stops for a leg.

    An explicit preference takes precedence. For ``AUTO``, use the shortest
    positive nonstop duration in the supplied options when available. If no
    nonstop duration exists and either airport lacks coordinates, use the
    shortest estimated airborne duration from the options, with a 0.5-hour
    minimum. Otherwise, estimate the nonstop duration from airport data.
    Durations below the policy threshold use the short-haul rule; durations
    at the threshold use the long-haul rule.

    Args:
        origin: Origin airport code used for duration estimation.
        destination: Destination airport code used for duration estimation.
        requested_stops: Explicit stop preference or ``AUTO``.
        policy: Stop limits and duration threshold for automatic selection.
        options: Optional candidate legs used to improve the duration estimate.

    Returns:
        An inclusive maximum of zero or one stop, or ``None`` for no stop limit.

    Examples:
        >>> from backend.app.models.schemas import StopsMode, StopsPolicy
        >>> from backend.app.solver.cabin import resolve_leg_max_stops
        >>> resolve_leg_max_stops("SFO", "LHR", StopsMode.ONE_STOP, StopsPolicy())
        1
        >>> resolve_leg_max_stops("SFO", "LHR", StopsMode.ANY, StopsPolicy()) is None
        True
    """
    if requested_stops != StopsMode.AUTO:
        return _stops_mode_to_limit(ConcreteStopsMode(requested_stops.value))

    est_hours: float | None = None
    if options:
        nonstop_durs = [o.duration_hours for o in options if o.stops_count == 0 and o.duration_hours > 0]
        if nonstop_durs:
            est_hours = min(nonstop_durs)
        elif not get_airport(origin).has_coordinates or not get_airport(destination).has_coordinates:
            air_durs = [max(0.5, o.duration_hours - o.layover_hours) for o in options if o.duration_hours > 0]
            if air_durs:
                est_hours = min(air_durs)

    if est_hours is None:
        est_hours = estimate_nonstop_hours(origin, destination)

    if est_hours < policy.nonstop_threshold_hours:
        return _stops_mode_to_limit(policy.short_haul_stops)
    return _stops_mode_to_limit(policy.long_haul_stops)


def filter_options_by_stops(
    options: list[FlightLegOption],
    max_stops: int | None,
    max_layover_hours: float | None = None,
) -> list[FlightLegOption]:
    """Filter options by preferred stops and average layover per stop.

    Apply the inclusive stop limit first. If nothing meets it, retain options
    with the fewest available stops. Then apply the inclusive average layover
    limit. If nothing meets that limit, retain options within half an hour of
    the shortest available average. A missing or nonpositive layover limit
    disables that filter. Individual connection durations are not checked.

    Args:
        options: Candidate legs in their preferred output order.
        max_stops: Preferred inclusive stop limit, or ``None`` for any number.
        max_layover_hours: Preferred maximum average layover hours per stop.

    Returns:
        Matching or relaxed candidates in their original order.

    Examples:
        This synthetic option shows how a nonstop preference can be relaxed:

        >>> from datetime import date
        >>> from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption
        >>> from backend.app.solver.cabin import filter_options_by_stops
        >>> option = FlightLegOption(
        ...     leg_id="one-stop", origin="SFO", destination="LHR",
        ...     departure_date=date(2026, 11, 10), cabin=ConcreteCabinClass.ECONOMY,
        ...     airline="XX", airline_name="Example Air", alliance="Non-Aligned",
        ...     flight_numbers=[], segments=[], duration_hours=10, stops_count=1,
        ...     layover_hours=2, one_way_base_fare_usd=500,
        ...     round_trip_half_fare_usd=400, bag_fee_per_checked_bag_usd=0,
        ... )
        >>> filter_options_by_stops([option], max_stops=0)[0].stops_count
        1
    """
    if not options:
        return options

    candidates = options
    if max_stops is not None:
        matching = [opt for opt in candidates if opt.stops_count <= max_stops]
        if matching:
            candidates = matching
        else:
            min_available = min(opt.stops_count for opt in candidates)
            candidates = [opt for opt in candidates if opt.stops_count == min_available]

    if max_layover_hours is None or max_layover_hours <= 0:
        return candidates

    within_layover = [
        opt for opt in candidates if opt.stops_count == 0 or (opt.layover_hours / opt.stops_count) <= max_layover_hours
    ]
    if within_layover:
        return within_layover

    min_layover = min(opt.layover_hours / max(1, opt.stops_count) for opt in candidates)
    return [opt for opt in candidates if (opt.layover_hours / max(1, opt.stops_count)) <= min_layover + 0.5]
