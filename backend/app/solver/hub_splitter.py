"""Evaluate heuristic hub splits of the first planned flight leg.

The strategy proposes a gateway open-jaw ticket, a separate hub continuation,
and any middle one-way tickets. It adds an assumed self-transfer buffer to
the score, but does not check the actual arrival and departure times at the
hub. Travelers must verify that the connection is feasible.
"""

from __future__ import annotations

from collections.abc import Callable

from backend.app.data.airports import candidate_intermediate_hubs, get_airport
from backend.app.models.queries import LegSearch
from backend.app.models.schemas import (
    BookedTicket,
    EvaluatedItinerary,
    FareEstimate,
    FlightLegOption,
    StrategyKind,
    TicketType,
    TripRequest,
)
from backend.app.providers.base import FlightSearchProvider
from backend.app.providers.pricing_engine import estimate_ticket_fare
from backend.app.solver.cabin import (
    filter_options_by_stops,
    resolve_leg_cabin,
    resolve_leg_max_stops,
)
from backend.app.solver.route_dag import CandidateSchedule, PlannedLegSpec


def required_self_transfer_buffer_hours(request: TripRequest) -> float:
    """Return the assumed self-transfer buffer in hours.

    Use 5.5 hours when the request includes checked baggage and 4.0 hours
    otherwise. This value is an allowance for scoring and guidance; it does
    not verify an actual connection.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.schemas import CityStopSpec, TripRequest
        >>> from backend.app.solver.hub_splitter import required_self_transfer_buffer_hours
        >>> trip = TripRequest(
        ...     origin_airports=["SFO"], destination_airports=["SFO"],
        ...     earliest_departure=date(2026, 11, 10), latest_return=date(2026, 11, 15),
        ...     stops=[CityStopSpec(id="lon", label="London", airports=["LHR"])],
        ... )
        >>> required_self_transfer_buffer_hours(trip)
        4.0
        >>> trip.baggage.checked_bags = 1
        >>> required_self_transfer_buffer_hours(trip)
        5.5
    """
    return 5.5 if request.baggage.checked_bags > 0 else 4.0


def _discover_corridor_hubs(
    orig_code: str,
    first_dest_code: str,
    first_leg_options: list[FlightLegOption],
    max_hubs: int = 2,
) -> list[str]:
    """Select hubs from observed layovers, then geographic corridor candidates.

    Rank observed hubs by descending frequency and then airport code. Exclude
    the endpoints and fill remaining slots with geographic candidates.
    """
    hub_counts: dict[str, int] = {}
    for opt in first_leg_options:
        for hub in opt.layover_airports:
            h_code = hub.strip().upper()
            if h_code and h_code not in (orig_code.upper(), first_dest_code.upper()):
                hub_counts[h_code] = hub_counts.get(h_code, 0) + 1

    discovered = [code for code, _ in sorted(hub_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    if len(discovered) < max_hubs:
        for fallback_hub in candidate_intermediate_hubs(orig_code, first_dest_code, max_hubs=max_hubs):
            if fallback_hub not in discovered:
                discovered.append(fallback_hub)
    return discovered[:max_hubs]


def evaluate_hub_split_candidates(
    schedule: CandidateSchedule,
    request: TripRequest,
    provider: FlightSearchProvider,
    compute_baggage_fee: Callable[[FlightLegOption, TripRequest], float],
    leg_generalized_cost: Callable[[FlightLegOption, TripRequest, bool], float],
    fetch_pair_options: Callable[[PlannedLegSpec, TripRequest, FlightSearchProvider], list[FlightLegOption]],
    assemble_itinerary: Callable[..., EvaluatedItinerary],
) -> EvaluatedItinerary | None:
    """Evaluate up to two hub splits for the first leg of a schedule.

    Skip this strategy when disabled, when the schedule has fewer than two
    legs, or when the first leg requires nonstop travel. A one-stop limit
    requires both split sub-legs to be nonstop. Select individual legs using
    the supplied cost function and return the lowest-scoring assembled
    candidate; this is not an exhaustive combination search.

    The selected sub-legs use the first leg's planned departure date. The
    assumed 4.0- or 5.5-hour buffer is added to the itinerary, but the
    selected flights' actual connection times are not checked. The gateway
    fare also includes a 6% discount assumption.

    Args:
        schedule: Candidate schedule whose first leg may be split.
        request: Trip preferences, baggage, and scoring weights.
        provider: Search provider; live searches must use a cache wrapper.
        compute_baggage_fee: Estimate the baggage fee for a leg and request.
        leg_generalized_cost: Rank a leg using one-way or half-round-trip fare.
        fetch_pair_options: Retrieve and filter options for a planned leg.
        assemble_itinerary: Build the evaluated itinerary from selected legs
            and proposed tickets.

    Returns:
        The best evaluated hub-split proposal, or ``None`` if none is found.
        Its ticket fares and connection feasibility are not verified.
    """
    if not request.weights.enable_hub_splitting or len(schedule.legs) < 2:
        return None

    first_spec = schedule.legs[0]
    last_spec = schedule.legs[-1]
    orig_code = first_spec.origin_airports[0]
    first_dest_code = first_spec.destination_airports[0]

    # Respect per-leg stop limits: if the user (or Auto Stops Policy) capped Leg 0 at
    # Nonstop (0 stops), do not split Leg 0 at an intermediate hub.
    first_max_stops = resolve_leg_max_stops(
        orig_code, first_dest_code, first_spec.requested_stops, request.stops_policy
    )
    if first_max_stops == 0:
        return None

    first_leg_options = fetch_pair_options(first_spec, request, provider)
    corridor_hubs = _discover_corridor_hubs(orig_code, first_dest_code, first_leg_options, max_hubs=2)
    if not corridor_hubs:
        return None

    min_buffer_hours = required_self_transfer_buffer_hours(request)
    best_itin: EvaluatedItinerary | None = None

    for hub_code in corridor_hubs:
        if hub_code in first_spec.destination_airports or hub_code in first_spec.origin_airports:
            continue
        hub_info = get_airport(hub_code)

        # Fetch Origin -> Hub (Leg 0a) and Hub -> Stop 1 (Leg 0b)
        cabin_0a = resolve_leg_cabin(orig_code, hub_code, first_spec.requested_cabin, request.cabin_policy)
        cabin_0b = resolve_leg_cabin(hub_code, first_dest_code, first_spec.requested_cabin, request.cabin_policy)
        raw_0a = list(
            provider.search(LegSearch.single(orig_code, hub_code, first_spec.departure_date, cabin_0a)).options
        )
        raw_0b = list(
            provider.search(LegSearch.single(hub_code, first_dest_code, first_spec.departure_date, cabin_0b)).options
        )
        if not raw_0a or not raw_0b:
            continue

        # Since splitting at `hub_code` already introduces 1 self-transfer, if `first_max_stops`
        # is 1, each sub-leg (Origin->Hub and Hub->Stop1) must be Nonstop (0 stops) so total
        # transfers on the split outbound do not exceed 1!
        sub_max_stops = 0 if first_max_stops == 1 else None
        if sub_max_stops == 0:
            opts_0a = [o for o in raw_0a if o.stops_count == 0]
            opts_0b = [o for o in raw_0b if o.stops_count == 0]
        else:
            opts_0a = filter_options_by_stops(
                raw_0a, sub_max_stops, max_layover_hours=request.stops_policy.max_layover_hours
            )
            opts_0b = filter_options_by_stops(
                raw_0b, sub_max_stops, max_layover_hours=request.stops_policy.max_layover_hours
            )
        if not opts_0a or not opts_0b:
            continue

        last_opts = fetch_pair_options(last_spec, request, provider)
        if not last_opts:
            continue

        best_0a = min(opts_0a, key=lambda o: leg_generalized_cost(o, request, True))
        best_0b = min(opts_0b, key=lambda o: leg_generalized_cost(o, request, False))

        matching_last = [
            o
            for o in last_opts
            if not o.is_lcc
            and (
                (best_0a.alliance in ("Star Alliance", "Oneworld", "SkyTeam") and o.alliance == best_0a.alliance)
                or (o.airline and o.airline.upper() == best_0a.airline.upper())
            )
        ]
        best_last = min(
            matching_last or last_opts,
            key=lambda o: leg_generalized_cost(o, request, bool(matching_last)),
        )

        # Middle legs
        middle_legs: list[FlightLegOption] = []
        middle_tickets: list[BookedTicket] = []
        possible = True
        for idx, spec in enumerate(schedule.legs[1:-1], start=1):
            m_opts = fetch_pair_options(spec, request, provider)
            if not m_opts:
                possible = False
                break
            best_m = min(m_opts, key=lambda o: leg_generalized_cost(o, request, False))
            middle_legs.append(best_m)
            fare_estimate = estimate_ticket_fare([best_m], TicketType.ONE_WAY)
            m_bag = compute_baggage_fee(best_m, request)
            middle_tickets.append(
                BookedTicket(
                    ticket_id=f"{schedule.schedule_id}-hub-mid-{idx}",
                    ticket_type=TicketType.ONE_WAY,
                    label=f"Ticket #{idx + 2}: Regional One-Way ({best_m.origin} → {best_m.destination})",
                    airline_or_alliance=f"{best_m.airline_name} ({best_m.alliance})",
                    cabin_summary=best_m.cabin.value.replace("_", " ").title(),
                    legs=[best_m],
                    leg_indices=[idx + 1],
                    fare_estimate=fare_estimate,
                    baggage_fees_usd=m_bag,
                    total_ticket_usd=round(fare_estimate.amount_usd + m_bag, 2),
                    pricing_note="Separate regional hop.",
                    booking_query_summary=(
                        f"Book One-Way: {best_m.origin}→{best_m.destination} on {best_m.departure_date.isoformat()}"
                    ),
                )
            )
        if not possible:
            continue

        # Estimate the gateway Open-Jaw fare from candidate-leg prices.
        anchor_fare = estimate_ticket_fare([best_0a, best_last], TicketType.OPEN_JAW)
        anchor_fare = FareEstimate(
            amount_usd=round(anchor_fare.amount_usd * 0.94, 2),
            assumptions=[*anchor_fare.assumptions, "Applies a 6% gateway-fare discount estimate."],
        )
        anchor_bags = round(compute_baggage_fee(best_0a, request) + compute_baggage_fee(best_last, request), 2)
        all_legs = [best_0a, best_0b, *middle_legs, best_last]

        anchor_ticket = BookedTicket(
            ticket_id=f"{schedule.schedule_id}-hub-anchor-{hub_code}",
            ticket_type=TicketType.OPEN_JAW,
            label=(
                f"Ticket #1: Hub Gateway Open-Jaw via {hub_code} "
                f"({best_0a.origin} → {hub_code} / {best_last.origin} → {best_last.destination})"
            ),
            airline_or_alliance=f"{best_0a.airline_name} ({best_0a.alliance})",
            cabin_summary=best_0a.cabin.value.replace("_", " ").title(),
            legs=[best_0a, best_last],
            leg_indices=[0, len(all_legs) - 1],
            fare_estimate=anchor_fare,
            baggage_fees_usd=anchor_bags,
            total_ticket_usd=round(anchor_fare.amount_usd + anchor_bags, 2),
            pricing_note=(
                f"Flies into major gateway hub {hub_code} ({hub_info.city}) to capture gateway fare, "
                f"returning from {best_last.origin}→{best_last.destination}."
            ),
            booking_query_summary=(
                f"Book Open-Jaw: {best_0a.origin}→{hub_code} ({best_0a.departure_date.isoformat()}) "
                f"& {best_last.origin}→{best_last.destination} ({best_last.departure_date.isoformat()})"
            ),
        )

        spoke_fare = estimate_ticket_fare([best_0b], TicketType.ONE_WAY)
        spoke_bag = compute_baggage_fee(best_0b, request)
        spoke_ticket = BookedTicket(
            ticket_id=f"{schedule.schedule_id}-hub-spoke-{hub_code}",
            ticket_type=TicketType.ONE_WAY,
            label=f"Ticket #2: Hub Continuation ({hub_code} → {best_0b.destination})",
            airline_or_alliance=f"{best_0b.airline_name} ({best_0b.alliance})",
            cabin_summary=best_0b.cabin.value.replace("_", " ").title(),
            legs=[best_0b],
            leg_indices=[1],
            fare_estimate=spoke_fare,
            baggage_fees_usd=spoke_bag,
            total_ticket_usd=round(spoke_fare.amount_usd + spoke_bag, 2),
            pricing_note=(
                f"Separate ticket connecting at {hub_code}. Requires ≥ {min_buffer_hours:.1f}h self-transfer buffer."
            ),
            booking_query_summary=(
                f"Book One-Way: {hub_code}→{best_0b.destination} on {best_0b.departure_date.isoformat()} "
                f"(allow ≥ {min_buffer_hours:.1f}h buffer at {hub_code})"
            ),
        )

        tickets = [anchor_ticket, spoke_ticket, *middle_tickets]
        itin = assemble_itinerary(
            itinerary_id=f"{schedule.schedule_id}-hubsplit-{hub_code.lower()}",
            strategy=StrategyKind.HUB_SPLIT,
            strategy_label=f"Hub-Split via {hub_code} ({hub_info.city})",
            strategy_description=(
                f"Splits outbound at gateway hub {hub_code} ({hub_info.city}) with a {min_buffer_hours:.1f}h self-transfer buffer."
            ),
            schedule=schedule,
            legs=all_legs,
            tickets=tickets,
            request=request,
            self_transfers=1,
            self_transfer_hubs=[hub_code],
            min_buffer_hours=min_buffer_hours,
            explanation_bullets=[
                f"Splits {orig_code}→{first_dest_code} at intermediate gateway hub {hub_code} ({hub_info.city}) onto a separate ticket.",
                f"Includes a mandatory {min_buffer_hours:.1f}h self-transfer buffer at {hub_code} "
                + (
                    "(extended for checked baggage claim & re-check)."
                    if request.baggage.checked_bags > 0
                    else "(carry-on only buffer)."
                ),
            ],
        )
        if best_itin is None or itin.effective_score < best_itin.effective_score:
            best_itin = itin

    return best_itin
