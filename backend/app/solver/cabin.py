"""Per-leg and duration-based cabin class and transfer limit resolver."""

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
    """Resolve a leg's concrete cabin class using either its explicit override or the duration rule."""
    if requested_cabin != CabinClass.AUTO:
        return ConcreteCabinClass(requested_cabin.value)

    est_hours = estimate_nonstop_hours(origin, destination)
    if est_hours >= policy.long_haul_threshold_hours:
        return policy.long_haul_cabin
    return policy.default_cabin


def highest_cabin(cabins: list[ConcreteCabinClass]) -> ConcreteCabinClass:
    """Return the highest cabin class among a set of legs (used when a single ticket must price uniformly)."""
    if not cabins:
        return ConcreteCabinClass.ECONOMY
    return max(cabins, key=lambda c: CABIN_RANK[c])


def _stops_mode_to_limit(mode: ConcreteStopsMode) -> int | None:
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
    """Resolve a leg's maximum allowed stops using either its explicit override or the duration rule.
    Uses actual flight durations from `options` when available (especially if airport coordinates are unknown).
    Returns 0 for Nonstop, 1 for <=1 Stop, or None for Any stops.
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
    """Filter candidate flight options to those matching `max_stops` and `max_layover_hours` per stop,
    gracefully falling back to the minimum stops / shortest layover available if no flight meets
    the strict bound.
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
