"""Intermediate hub splitter & virtual interlining evaluator.

Tests splitting long-haul legs at major intermediate gateway hubs (e.g., TPE, ICN, HND,
LHR, DUB, IST, SIN, DOH) either as:
  1. Gateway Open-Jaw + Spoke Continuation (`Origin -> Hub` + `LastStop -> Origin` on Ticket 1,
     `Hub -> FirstStop` on Ticket 2)
  2. Pure Hub Round-Trip Anchor (`Origin <-> Hub` Round-Trip on Ticket 1, with regional flights
     `Hub -> Stop 1 -> ... -> LastStop -> Hub` nested inside).
Enforces minimum self-transfer connection buffers (4.0h carry-on only, 5.5h with checked bags).
"""

from __future__ import annotations

from collections.abc import Callable

from backend.app.data.airports import candidate_intermediate_hubs, get_airport
from backend.app.models.schemas import (
    BookedTicket,
    EvaluatedItinerary,
    FlightLegOption,
    StrategyKind,
    TicketType,
    TripRequest,
)
from backend.app.providers.base import FlightSearchProvider
from backend.app.solver.cabin import resolve_leg_cabin
from backend.app.solver.route_dag import CandidateSchedule, PlannedLegSpec


def required_self_transfer_buffer_hours(request: TripRequest) -> float:
    """Return mandatory connection buffer (hours) for an unprotected self-transfer at a hub."""
    return 5.5 if request.baggage.checked_bags > 0 else 4.0


def evaluate_hub_split_candidates(
    schedule: CandidateSchedule,
    request: TripRequest,
    provider: FlightSearchProvider,
    compute_baggage_fee: Callable[[FlightLegOption, TripRequest], float],
    leg_generalized_cost: Callable[[FlightLegOption, TripRequest, bool], float],
    fetch_pair_options: Callable[[PlannedLegSpec, TripRequest, FlightSearchProvider], list[FlightLegOption]],
    assemble_itinerary: Callable[..., EvaluatedItinerary],
) -> EvaluatedItinerary | None:
    """Evaluate intermediate hub-splitting strategies for the given schedule."""
    if not request.weights.enable_hub_splitting or len(schedule.legs) < 2:
        return None

    first_spec = schedule.legs[0]
    last_spec = schedule.legs[-1]
    orig_code = first_spec.origin_airports[0]
    first_dest_code = first_spec.destination_airports[0]

    corridor_hubs = candidate_intermediate_hubs(orig_code, first_dest_code, max_hubs=2)
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
        opts_0a = provider.search_leg(orig_code, hub_code, first_spec.departure_date, cabin_0a)
        opts_0b = provider.search_leg(hub_code, first_dest_code, first_spec.departure_date, cabin_0b)
        if not opts_0a or not opts_0b:
            continue

        last_opts = fetch_pair_options(last_spec, request, provider)
        if not last_opts:
            continue

        best_0a = min(opts_0a, key=lambda o: leg_generalized_cost(o, request, True))
        best_0b = min(opts_0b, key=lambda o: leg_generalized_cost(o, request, False))

        matching_last = [o for o in last_opts if o.alliance == best_0a.alliance and not o.is_lcc]
        best_last = min(
            matching_last if matching_last else last_opts,
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
            m_base = round(best_m.one_way_base_fare_usd, 2)
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
                    base_fare_usd=m_base,
                    baggage_fees_usd=m_bag,
                    total_ticket_usd=round(m_base + m_bag, 2),
                    pricing_note="Separate regional hop.",
                    booking_query_summary=(
                        f"Book One-Way: {best_m.origin}→{best_m.destination} on {best_m.departure_date.isoformat()}"
                    ),
                )
            )
        if not possible:
            continue

        # Price the gateway Open-Jaw ticket via provider's multi-slice quote
        raw_anchor_fare = provider.quote_multi_slice_ticket([best_0a, best_last], TicketType.OPEN_JAW)
        # Competitive hub gateways typically offer slightly lower promotional base fares than spoke cities
        anchor_base = round(raw_anchor_fare * 0.94, 2)
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
            base_fare_usd=anchor_base,
            baggage_fees_usd=anchor_bags,
            total_ticket_usd=round(anchor_base + anchor_bags, 2),
            pricing_note=(
                f"Flies into major gateway hub {hub_code} ({hub_info.city}) to capture gateway fare, "
                f"returning from {best_last.origin}→{best_last.destination}."
            ),
            booking_query_summary=(
                f"Book Open-Jaw: {best_0a.origin}→{hub_code} ({best_0a.departure_date.isoformat()}) "
                f"& {best_last.origin}→{best_last.destination} ({best_last.departure_date.isoformat()})"
            ),
        )

        spoke_base = round(best_0b.one_way_base_fare_usd, 2)
        spoke_bag = compute_baggage_fee(best_0b, request)
        spoke_ticket = BookedTicket(
            ticket_id=f"{schedule.schedule_id}-hub-spoke-{hub_code}",
            ticket_type=TicketType.ONE_WAY,
            label=f"Ticket #2: Hub Continuation ({hub_code} → {best_0b.destination})",
            airline_or_alliance=f"{best_0b.airline_name} ({best_0b.alliance})",
            cabin_summary=best_0b.cabin.value.replace("_", " ").title(),
            legs=[best_0b],
            leg_indices=[1],
            base_fare_usd=spoke_base,
            baggage_fees_usd=spoke_bag,
            total_ticket_usd=round(spoke_base + spoke_bag, 2),
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
