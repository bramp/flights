"""Generate sampled city orders and date-based schedule candidates.

Despite the module name, this implementation samples representative orders,
start dates, and stay lengths rather than exhaustively searching a route DAG.
Planned stop arrivals use the inbound leg's departure date, not its actual
flight arrival time.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date, timedelta

from backend.app.data.airports import haversine_km
from backend.app.models.schemas import (
    CabinClass,
    CityStopSpec,
    ScheduledStopVisit,
    StopsMode,
    TripRequest,
)


@dataclass(frozen=True)
class PlannedLegSpec:
    """Describe one planned flight leg before candidate flights are selected.

    Attributes:
        leg_index: Zero-based position in the planned itinerary.
        origin_airports: Allowed origin airport codes in priority order.
        destination_airports: Allowed destination codes in priority order.
        departure_date: Planned departure date.
        requested_cabin: Cabin preference for the leg, including ``AUTO``.
        from_label: Display label for the origin.
        to_label: Display label for the destination.
        requested_stops: Preferred stop limit, defaulting to ``AUTO``.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.schemas import CabinClass
        >>> from backend.app.solver.route_dag import PlannedLegSpec
        >>> leg = PlannedLegSpec(
        ...     leg_index=0, origin_airports=("SFO",), destination_airports=("LHR",),
        ...     departure_date=date(2026, 11, 10), requested_cabin=CabinClass.ECONOMY,
        ...     from_label="San Francisco", to_label="London",
        ... )
        >>> leg.requested_stops.value
        'auto'
    """

    leg_index: int
    origin_airports: tuple[str, ...]
    destination_airports: tuple[str, ...]
    departure_date: date
    requested_cabin: CabinClass
    from_label: str
    to_label: str
    requested_stops: StopsMode = StopsMode.AUTO


@dataclass(frozen=True)
class CandidateSchedule:
    """Group a city order, planned visits, and legs for evaluation.

    The dataclass prevents field reassignment but does not freeze the nested
    stop and visit models. Dates are planned dates, not verified flight times.

    Attributes:
        schedule_id: Identifier for the sampled or fallback schedule.
        ordered_stops: Requested stops in the proposed visit order.
        stop_visits: Planned arrival and departure dates for each stop.
        legs: Planned flight legs in travel order, including the final leg.
        total_route_km: Approximate route distance in kilometers. Generated
            schedules use each leg's first airport and round to one decimal.
    """

    schedule_id: str
    ordered_stops: tuple[CityStopSpec, ...]
    stop_visits: tuple[ScheduledStopVisit, ...]
    legs: tuple[PlannedLegSpec, ...]
    total_route_km: float


def generate_city_orders(request: TripRequest) -> list[tuple[CityStopSpec, ...]]:
    """Generate up to four candidate city visit orders.

    Fixed mode retains the input order. Flexible mode retains pinned stops at
    their input positions; automatic TSP mode permits all stops to move.
    Permutations that fail a preliminary neighboring date-window check are
    excluded, then ranked by approximate distance between primary airports.
    The original order is retained even if it failed that preliminary check.
    These orders are a sample, not a proof of the best order by fare or time.

    Args:
        request: Trip stops, ordering mode, and endpoint airports.

    Returns:
        Candidate stop tuples in the order selected for evaluation.
    """
    stops = list(request.stops)
    n = len(stops)
    if n <= 1 or request.ordering_mode == "fixed":
        return [tuple(stops)]

    if request.ordering_mode == "flexible":
        fixed_indices = {i for i, s in enumerate(stops) if s.fixed_order}
        unlocked = [s for i, s in enumerate(stops) if i not in fixed_indices]
    else:
        # auto_tsp: all stops can be reordered
        fixed_indices = set()
        unlocked = list(stops)

    if len(unlocked) <= 1:
        return [tuple(stops)]

    # Cap permutations by geographic TSP distance if there are many unlocked stops
    origin_primary = request.origin_airports[0]
    dest_primary = request.destination_airports[0]

    scored_orders: list[tuple[float, tuple[CityStopSpec, ...]]] = []
    for perm in itertools.permutations(unlocked):
        perm_iter = iter(perm)
        assembled: list[CityStopSpec] = []
        for idx in range(n):
            if idx in fixed_indices:
                assembled.append(stops[idx])
            else:
                assembled.append(next(perm_iter))

        # Quick feasibility check on date windows if specified
        feasible = True
        for i in range(len(assembled) - 1):
            curr_stop = assembled[i]
            next_stop = assembled[i + 1]
            if (
                curr_stop.earliest_arrival
                and next_stop.latest_departure
                and curr_stop.earliest_arrival >= next_stop.latest_departure
            ):
                feasible = False
                break
        if not feasible:
            continue

        # Compute approximate great-circle circuit length
        total_km = 0.0
        prev_code = origin_primary
        for stop in assembled:
            code = stop.airports[0]
            total_km += haversine_km(prev_code, code)
            prev_code = code
        total_km += haversine_km(prev_code, dest_primary)
        scored_orders.append((total_km, tuple(assembled)))

    scored_orders.sort(key=lambda item: item[0])
    # Always keep the user's original order plus the top shortest geographic permutations
    original_tuple = tuple(stops)
    top_orders = [order for _, order in scored_orders[:4]]
    if original_tuple not in top_orders:
        top_orders.insert(0, original_tuple)
    return top_orders[:4]


def generate_candidate_schedules(
    request: TripRequest,
    max_schedules: int = 12,
) -> list[CandidateSchedule]:
    """Generate a bounded sample of date-based candidate schedules.

    For each selected city order, test representative start offsets and
    minimum, midpoint, or maximum stay profiles. The normal candidates use
    inclusive trip and stop date bounds. When the total window is shorter
    than the requested minimum stays, the sampled minimum stays are compressed.
    Planned stop arrivals use the inbound leg's departure date and do not
    account for overnight flights.

    If no sampled candidate meets the date checks, return a relaxed fallback.
    It can violate stop windows and, when there are too few days for one night
    per stop, can depart on the final leg after ``latest_return``. Callers
    should surface the fallback and verify the actual flight dates.

    Args:
        request: Trip dates, stops, airport choices, and ordering preferences.
        max_schedules: Maximum number of distinct schedules when positive.

    Returns:
        Schedules in generation order, deduplicated by stop IDs and leg
        departure dates. A nonpositive limit can still return one schedule.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.schemas import CityStopSpec, TripRequest
        >>> from backend.app.solver.route_dag import generate_candidate_schedules
        >>> trip = TripRequest(
        ...     origin_airports=["SFO"], destination_airports=["SFO"],
        ...     earliest_departure=date(2026, 11, 10), latest_return=date(2026, 11, 16),
        ...     stops=[CityStopSpec(id="lon", label="London", airports=["LHR"], min_nights=2, max_nights=2)],
        ... )
        >>> schedule = generate_candidate_schedules(trip, max_schedules=1)[0]
        >>> schedule.legs[0].origin_airports, schedule.stop_visits[0].nights
        (('SFO',), 2)

        A short window can produce a fallback beyond the requested final date:

        >>> short_trip = TripRequest(
        ...     origin_airports=["SFO"], destination_airports=["SFO"],
        ...     earliest_departure=date(2026, 11, 10), latest_return=date(2026, 11, 11),
        ...     stops=[
        ...         CityStopSpec(id="lon", label="London", airports=["LHR"], min_nights=1, max_nights=1),
        ...         CityStopSpec(id="par", label="Paris", airports=["CDG"], min_nights=1, max_nights=1),
        ...     ],
        ... )
        >>> fallback = generate_candidate_schedules(short_trip, max_schedules=1)[0]
        >>> fallback.schedule_id, fallback.legs[-1].departure_date.isoformat()
        ('sched-fallback-0', '2026-11-12')
    """
    orders = generate_city_orders(request)
    candidates: list[CandidateSchedule] = []

    total_window_days = (request.latest_return - request.earliest_departure).days
    min_total_nights = sum(s.min_nights for s in request.stops)

    if total_window_days < min_total_nights:
        # Gracefully compress stay durations so user still gets solutions with a warning
        scale = max(1, total_window_days // max(1, len(request.stops)))
        adjusted_min = [scale for _ in request.stops]
    else:
        adjusted_min = None

    for order_idx, stops_order in enumerate(orders):
        n = len(stops_order)
        mins = [adjusted_min[i] if adjusted_min else s.min_nights for i, s in enumerate(stops_order)]
        maxs = [max(mins[i], s.max_nights) for i, s in enumerate(stops_order)]

        # Sample representative start offsets within the allowed departure range
        max_dep_date = request.latest_departure or request.latest_return
        max_dep_offset = max(0, (max_dep_date - request.earliest_departure).days)
        slack_days = min(max_dep_offset, max(0, total_window_days - sum(mins)))
        start_offsets = sorted(
            {0, min(1, slack_days), min(2, slack_days), min(4, slack_days), slack_days // 2, slack_days}
        )

        duration_profiles: list[list[int]] = [mins]
        # Midpoint nights profile
        mids = [(mins[i] + maxs[i]) // 2 for i in range(n)]
        if sum(mids) <= total_window_days and mids not in duration_profiles:
            duration_profiles.append(mids)
        # Max nights profile (clamped to total_window_days)
        if sum(maxs) <= total_window_days and maxs not in duration_profiles:
            duration_profiles.append(maxs)

        for offset in start_offsets:
            start_date = request.earliest_departure + timedelta(days=offset)
            if request.latest_departure and start_date > request.latest_departure:
                continue
            for prof_idx, nights_list in enumerate(duration_profiles):
                return_date = start_date + timedelta(days=sum(nights_list))
                if return_date > request.latest_return:
                    continue
                if request.earliest_return and return_date < request.earliest_return:
                    continue

                cur_date = start_date
                visits: list[ScheduledStopVisit] = []
                legs: list[PlannedLegSpec] = []
                window_ok = True

                for i, stop in enumerate(stops_order):
                    arr_date = cur_date
                    dep_date = arr_date + timedelta(days=nights_list[i])

                    if stop.earliest_arrival and arr_date < stop.earliest_arrival:
                        window_ok = False
                        break
                    if stop.latest_departure and dep_date > stop.latest_departure:
                        window_ok = False
                        break

                    from_airports = tuple(request.origin_airports) if i == 0 else tuple(stops_order[i - 1].airports)
                    from_label = request.origin_label if i == 0 else stops_order[i - 1].label

                    legs.append(
                        PlannedLegSpec(
                            leg_index=i,
                            origin_airports=from_airports,
                            destination_airports=tuple(stop.airports),
                            departure_date=arr_date,
                            requested_cabin=stop.outbound_cabin,
                            from_label=from_label,
                            to_label=stop.label,
                            requested_stops=stop.outbound_stops,
                        )
                    )
                    visits.append(
                        ScheduledStopVisit(
                            stop_id=stop.id,
                            label=stop.label,
                            arrival_airport=stop.airports[0],
                            departure_airport=stop.airports[0],
                            arrival_date=arr_date,
                            departure_date=dep_date,
                            nights=nights_list[i],
                        )
                    )
                    cur_date = dep_date

                if not window_ok:
                    continue

                # Final return leg back to destination
                last_stop = stops_order[-1]
                legs.append(
                    PlannedLegSpec(
                        leg_index=n,
                        origin_airports=tuple(last_stop.airports),
                        destination_airports=tuple(request.destination_airports),
                        departure_date=cur_date,
                        requested_cabin=request.return_leg_cabin,
                        from_label=last_stop.label,
                        to_label=request.destination_label,
                        requested_stops=request.return_leg_stops,
                    )
                )

                # Calculate route distance
                route_km = 0.0
                for leg in legs:
                    route_km += haversine_km(leg.origin_airports[0], leg.destination_airports[0])

                sched_id = f"sched-{order_idx}-{offset}-{prof_idx}"
                candidates.append(
                    CandidateSchedule(
                        schedule_id=sched_id,
                        ordered_stops=stops_order,
                        stop_visits=tuple(visits),
                        legs=tuple(legs),
                        total_route_km=round(route_km, 1),
                    )
                )

    # If strict stop/return date windows pruned every candidate, build a relaxed fallback
    # schedule so the solver can still return an itinerary alongside a warning.
    if not candidates and orders:
        stops_order = orders[0]
        n = len(stops_order)
        fallback_nights = [max(1, min(s.min_nights, max(1, total_window_days // max(1, n)))) for s in stops_order]
        cur_date = request.earliest_departure
        visits = []
        legs = []
        for i, stop in enumerate(stops_order):
            arr_date = cur_date
            dep_date = min(request.latest_return, arr_date + timedelta(days=fallback_nights[i]))
            if dep_date <= arr_date:
                dep_date = arr_date + timedelta(days=1)
            from_airports = tuple(request.origin_airports) if i == 0 else tuple(stops_order[i - 1].airports)
            from_label = request.origin_label if i == 0 else stops_order[i - 1].label
            legs.append(
                PlannedLegSpec(
                    leg_index=i,
                    origin_airports=from_airports,
                    destination_airports=tuple(stop.airports),
                    departure_date=arr_date,
                    requested_cabin=stop.outbound_cabin,
                    from_label=from_label,
                    to_label=stop.label,
                    requested_stops=stop.outbound_stops,
                )
            )
            visits.append(
                ScheduledStopVisit(
                    stop_id=stop.id,
                    label=stop.label,
                    arrival_airport=stop.airports[0],
                    departure_airport=stop.airports[0],
                    arrival_date=arr_date,
                    departure_date=dep_date,
                    nights=(dep_date - arr_date).days,
                )
            )
            cur_date = dep_date

        last_stop = stops_order[-1]
        legs.append(
            PlannedLegSpec(
                leg_index=n,
                origin_airports=tuple(last_stop.airports),
                destination_airports=tuple(request.destination_airports),
                departure_date=cur_date,
                requested_cabin=request.return_leg_cabin,
                from_label=last_stop.label,
                to_label=request.destination_label,
                requested_stops=request.return_leg_stops,
            )
        )
        route_km = sum(haversine_km(leg.origin_airports[0], leg.destination_airports[0]) for leg in legs)
        candidates.append(
            CandidateSchedule(
                schedule_id="sched-fallback-0",
                ordered_stops=stops_order,
                stop_visits=tuple(visits),
                legs=tuple(legs),
                total_route_km=round(route_km, 1),
            )
        )

    # Deduplicate by (stop_ids, leg_dates) and return up to max_schedules
    unique: list[CandidateSchedule] = []
    seen_keys: set[tuple[object, ...]] = set()
    for cand in candidates:
        key = (
            tuple(s.id for s in cand.ordered_stops),
            tuple(leg.departure_date.isoformat() for leg in cand.legs),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(cand)
        if len(unique) >= max_schedules:
            break

    return unique
