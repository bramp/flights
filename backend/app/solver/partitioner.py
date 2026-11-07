"""Set-partitioning solver for multi-city flight itineraries."""

from __future__ import annotations

from collections.abc import Callable

from backend.app.models.schemas import (
    BookedTicket,
    ConcreteCabinClass,
    EvaluatedItinerary,
    FlightLegOption,
    ScheduledStopVisit,
    StrategyKind,
    TicketType,
    TripRequest,
)
from backend.app.providers.base import FlightSearchProvider
from backend.app.solver.cabin import (
    filter_options_by_stops,
    highest_cabin,
    resolve_leg_cabin,
    resolve_leg_max_stops,
)
from backend.app.solver.hub_splitter import evaluate_hub_split_candidates
from backend.app.solver.pareto import compute_effective_score
from backend.app.solver.route_dag import CandidateSchedule, PlannedLegSpec

MAJOR_ALLIANCES = ("Star Alliance", "Oneworld", "SkyTeam")


def _compute_baggage_fee(leg: FlightLegOption, request: TripRequest) -> float:
    fee = 0.0
    if request.baggage.checked_bags > 0:
        fee += leg.bag_fee_per_checked_bag_usd * request.baggage.checked_bags
    if request.baggage.include_carry_on and not leg.includes_carry_on:
        fee += 35.0
    return round(fee, 2)


def _fetch_all_airport_pair_options(
    leg_spec: PlannedLegSpec,
    request: TripRequest,
    provider: FlightSearchProvider,
    cabin_override: ConcreteCabinClass | None = None,
) -> list[FlightLegOption]:
    """Query allowed (origin_airport, destination_airport) pairs for a planned leg,
    using batched search when supported by the provider, and filter by the leg's resolved max_stops.
    """
    origs = leg_spec.origin_airports
    dests = leg_spec.destination_airports
    if not origs or not dests:
        return []
    if len(origs) == 1 and len(dests) == 1 and origs[0].upper() == dests[0].upper():
        return []
    cabin = cabin_override or resolve_leg_cabin(origs[0], dests[0], leg_spec.requested_cabin, request.cabin_policy)
    raw_options = provider.search_leg_batch(origs, dests, leg_spec.departure_date, cabin)
    max_stops = resolve_leg_max_stops(
        origs[0], dests[0], leg_spec.requested_stops, request.stops_policy, options=raw_options
    )
    return filter_options_by_stops(raw_options, max_stops)


def _slug(label: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in label).strip("-") or "group"


def _candidate_carrier_groups(
    options_by_slice: list[list[FlightLegOption]],
) -> list[tuple[str, list[list[FlightLegOption]]]]:
    """Return candidate (group_label, filtered_options_per_slice) groups that can be booked
    onto a single multi-slice ticket:
    1. Major airline alliances (Star Alliance, Oneworld, SkyTeam) present across all slices.
    2. Individual non-aligned, non-LCC carriers (by airline code) present across all slices,
       so airlines returned by Google Flights can form Round-Trip, Open-Jaw, Nested, or
       Multi-City tickets without requiring hardcoded alliance tables.
    """
    if not options_by_slice or any(not opts for opts in options_by_slice):
        return []

    groups: list[tuple[str, list[list[FlightLegOption]]]] = []
    for alliance in MAJOR_ALLIANCES:
        per_slice = [[o for o in opts if o.alliance == alliance and not o.is_lcc] for opts in options_by_slice]
        if all(per_slice):
            groups.append((alliance, per_slice))

    carrier_names: dict[str, str] = {}
    for o in options_by_slice[0]:
        if not o.is_lcc and o.alliance not in MAJOR_ALLIANCES and o.airline.strip():
            carrier_names.setdefault(o.airline.strip().upper(), o.airline_name)

    for code, name in sorted(carrier_names.items()):
        per_slice = [
            [o for o in opts if o.airline.strip().upper() == code and not o.is_lcc] for opts in options_by_slice
        ]
        if all(per_slice):
            label = name if name and name != "Airline" else code
            groups.append((label, per_slice))

    return groups


def _leg_generalized_cost(
    leg: FlightLegOption,
    request: TripRequest,
    use_rt_half_fare: bool = False,
) -> float:
    fare = leg.round_trip_half_fare_usd if use_rt_half_fare else leg.one_way_base_fare_usd
    bag = _compute_baggage_fee(leg, request)
    time_cost = leg.duration_hours * request.weights.value_of_time_per_hour
    transfer_cost = leg.stops_count * request.weights.protected_transfer_penalty
    return fare + bag + time_cost + transfer_cost


def _build_updated_visits(
    schedule: CandidateSchedule,
    chosen_legs: list[FlightLegOption],
) -> list[ScheduledStopVisit]:
    """Update each stop's actual arrival and departure airport based on the selected flights."""
    # When Leg 0 is hub-split into [Origin->Hub, Hub->Stop1], collapse the first two legs
    # so index 0 corresponds to the leg arriving at Stop 1.
    effective_legs = chosen_legs[1:] if len(chosen_legs) == len(schedule.legs) + 1 else chosen_legs
    updated: list[ScheduledStopVisit] = []
    for idx, visit in enumerate(schedule.stop_visits):
        arr_airport = effective_legs[idx].destination if idx < len(effective_legs) else visit.arrival_airport
        dep_airport = effective_legs[idx + 1].origin if (idx + 1) < len(effective_legs) else visit.departure_airport
        updated.append(
            visit.model_copy(
                update={
                    "arrival_airport": arr_airport,
                    "departure_airport": dep_airport,
                }
            )
        )
    return updated


def _assemble_itinerary(
    itinerary_id: str,
    strategy: StrategyKind,
    strategy_label: str,
    strategy_description: str,
    schedule: CandidateSchedule,
    legs: list[FlightLegOption],
    tickets: list[BookedTicket],
    request: TripRequest,
    self_transfers: int = 0,
    self_transfer_hubs: list[str] | None = None,
    min_buffer_hours: float | None = None,
    explanation_bullets: list[str] | None = None,
) -> EvaluatedItinerary:
    total_base = round(sum(t.base_fare_usd for t in tickets), 2)
    total_bags = round(sum(t.baggage_fees_usd for t in tickets), 2)
    total_price = round(total_base + total_bags, 2)

    total_layover = round(sum(leg.layover_hours for leg in legs), 2)
    if self_transfers > 0 and min_buffer_hours:
        total_layover = round(total_layover + (self_transfers * min_buffer_hours), 2)

    total_flight_hrs = round(sum(leg.duration_hours - leg.layover_hours for leg in legs), 2)
    total_travel_hrs = round(total_flight_hrs + total_layover, 2)
    protected_transfers = sum(leg.stops_count for leg in legs)

    # Check if any stop has a cross-airport ground transfer during the city stay (e.g. NRT -> HND)
    visits = _build_updated_visits(schedule, legs)
    route_codes = [legs[0].origin] + [leg.destination for leg in legs]
    route_summary = " → ".join(route_codes)

    effective_score = compute_effective_score(
        total_price_usd=total_price,
        total_travel_hours=total_travel_hrs,
        protected_transfers=protected_transfers,
        self_transfers=self_transfers,
        tickets_count=len(tickets),
        weights=request.weights,
    )

    return EvaluatedItinerary(
        itinerary_id=itinerary_id,
        strategy=strategy,
        strategy_label=strategy_label,
        strategy_description=strategy_description,
        route_summary=route_summary,
        stop_visits=visits,
        legs=legs,
        tickets=tickets,
        total_base_fare_usd=total_base,
        total_baggage_fees_usd=total_bags,
        total_price_usd=total_price,
        total_travel_hours=total_travel_hrs,
        total_flight_hours=total_flight_hrs,
        total_layover_hours=total_layover,
        protected_transfers=protected_transfers,
        self_transfers=self_transfers,
        self_transfer_hubs=self_transfer_hubs or [],
        min_self_transfer_buffer_hours=min_buffer_hours,
        effective_score=effective_score,
        explanation_bullets=explanation_bullets or [],
    )


def evaluate_single_multi_city_ticket(
    schedule: CandidateSchedule,
    request: TripRequest,
    provider: FlightSearchProvider,
) -> EvaluatedItinerary | None:
    """Strategy 1: Book all trip legs on a single Multi-City PNR within one airline alliance.
    Note: Single-ticket multi-city itineraries require a consistent alliance and often price
    at the highest cabin class requested across the long-haul/regional combination, or incur a
    multi-slice combinability surcharge if mixing cabins/regions.
    """
    desired_cabins = [
        resolve_leg_cabin(
            leg.origin_airports[0],
            leg.destination_airports[0],
            leg.requested_cabin,
            request.cabin_policy,
        )
        for leg in schedule.legs
    ]
    uniform_cabin = highest_cabin(desired_cabins)
    has_mixed_cabin_request = len(set(desired_cabins)) > 1

    best_itinerary: EvaluatedItinerary | None = None
    all_slice_options = [
        _fetch_all_airport_pair_options(leg_spec, request, provider, cabin_override=uniform_cabin)
        for leg_spec in schedule.legs
    ]

    for alliance, per_slice_opts in _candidate_carrier_groups(all_slice_options):
        chosen_legs = [
            min(slice_opts, key=lambda o: _leg_generalized_cost(o, request, use_rt_half_fare=True))
            for slice_opts in per_slice_opts
        ]

        base_fare = provider.quote_multi_slice_ticket(chosen_legs, TicketType.MULTI_CITY)
        bag_fees = round(sum(_compute_baggage_fee(leg, request) * 0.75 for leg in chosen_legs), 2)
        slices_str = ", ".join(
            f"{leg.origin}→{leg.destination} ({leg.departure_date.isoformat()})" for leg in chosen_legs
        )
        ticket = BookedTicket(
            ticket_id=f"{schedule.schedule_id}-mc-{_slug(alliance)}",
            ticket_type=TicketType.MULTI_CITY,
            label=f"Single Multi-City Ticket ({alliance})",
            airline_or_alliance=alliance,
            cabin_summary=uniform_cabin.value.replace("_", " ").title(),
            legs=chosen_legs,
            leg_indices=list(range(len(chosen_legs))),
            base_fare_usd=base_fare,
            baggage_fees_usd=bag_fees,
            total_ticket_usd=round(base_fare + bag_fees, 2),
            pricing_note=(
                f"All {len(chosen_legs)} legs booked on one {alliance} Multi-City PNR in "
                f"{uniform_cabin.value.replace('_', ' ').title()}."
                + (
                    " (Single-PNR rules price all slices at the highest cabin class)."
                    if has_mixed_cabin_request
                    else ""
                )
            ),
            booking_query_summary=f"Book 1 Multi-City ticket: {slices_str}",
        )

        bullets = [
            f"1 single {alliance} ticket covering all {len(chosen_legs)} flights — protected connections & through-checked bags.",
        ]
        if has_mixed_cabin_request:
            bullets.append(
                f"Because you requested {uniform_cabin.value.replace('_', ' ').title()} on long-haul legs, "
                "a single all-in-one ticket prices regional legs in that higher fare bucket too."
            )

        itin = _assemble_itinerary(
            itinerary_id=f"{schedule.schedule_id}-single-{_slug(alliance)}",
            strategy=StrategyKind.SINGLE_TICKET,
            strategy_label="1 Single Multi-City Ticket",
            strategy_description="All flights on a single alliance booking (1 PNR) with full connection protection.",
            schedule=schedule,
            legs=chosen_legs,
            tickets=[ticket],
            request=request,
            explanation_bullets=bullets,
        )
        if best_itinerary is None or itin.effective_score < best_itinerary.effective_score:
            best_itinerary = itin

    return best_itinerary


def evaluate_all_one_ways(
    schedule: CandidateSchedule,
    request: TripRequest,
    provider: FlightSearchProvider,
) -> EvaluatedItinerary | None:
    """Strategy 2: Book each leg as an independent One-Way ticket in its exact target cabin."""
    chosen_legs: list[FlightLegOption] = []
    tickets: list[BookedTicket] = []

    for idx, leg_spec in enumerate(schedule.legs):
        options = _fetch_all_airport_pair_options(leg_spec, request, provider)
        if not options:
            return None
        best_leg = min(
            options,
            key=lambda o: _leg_generalized_cost(o, request, use_rt_half_fare=False),
        )
        chosen_legs.append(best_leg)
        base_fare = round(best_leg.one_way_base_fare_usd, 2)
        bag_fee = _compute_baggage_fee(best_leg, request)
        tickets.append(
            BookedTicket(
                ticket_id=f"{schedule.schedule_id}-ow-{idx}",
                ticket_type=TicketType.ONE_WAY,
                label=f"Ticket #{idx + 1}: One-Way ({best_leg.origin} → {best_leg.destination})",
                airline_or_alliance=f"{best_leg.airline_name} ({best_leg.alliance})",
                cabin_summary=best_leg.cabin.value.replace("_", " ").title(),
                legs=[best_leg],
                leg_indices=[idx],
                base_fare_usd=base_fare,
                baggage_fees_usd=bag_fee,
                total_ticket_usd=round(base_fare + bag_fee, 2),
                pricing_note=(
                    "Point-to-point LCC one-way fare."
                    if best_leg.is_lcc
                    else "Standard one-way carrier fare (includes one-way long-haul markup if intercontinental)."
                ),
                booking_query_summary=(
                    f"Book One-Way: {best_leg.origin} → {best_leg.destination} on {best_leg.departure_date.isoformat()} "
                    f"({best_leg.airline_name}, {best_leg.cabin.value.replace('_', ' ').title()})"
                ),
            )
        )

    bullets = [
        f"Booked as {len(tickets)} separate One-Way tickets, picking the cheapest/fastest carrier on every individual leg.",
        "Allows mixing Low-Cost Carriers (LCCs) and exact per-leg cabin classes, but incurs legacy carrier One-Way surcharges on intercontinental flights.",
    ]

    return _assemble_itinerary(
        itinerary_id=f"{schedule.schedule_id}-all-ow",
        strategy=StrategyKind.ALL_ONE_WAYS,
        strategy_label=f"{len(tickets)} Separate One-Way Tickets",
        strategy_description="Every city-to-city leg booked as its own separate One-Way ticket.",
        schedule=schedule,
        legs=chosen_legs,
        tickets=tickets,
        request=request,
        explanation_bullets=bullets,
    )


def evaluate_open_jaw_plus_regional(
    schedule: CandidateSchedule,
    request: TripRequest,
    provider: FlightSearchProvider,
) -> EvaluatedItinerary | None:
    """Strategy 3: Combine the outbound anchor leg (Leg 0) and return anchor leg (Leg N-1)
    into a single Open-Jaw or Round-Trip ticket on one alliance, and book middle regional hops
    as separate One-Way tickets in their respective cabins.
    """
    if len(schedule.legs) < 2:
        return None

    first_spec = schedule.legs[0]
    last_spec = schedule.legs[-1]
    middle_specs = schedule.legs[1:-1]

    # Pick the best middle legs first (as independent One-Ways in their exact requested cabin)
    middle_legs: list[FlightLegOption] = []
    middle_tickets: list[BookedTicket] = []
    for offset, leg_spec in enumerate(middle_specs, start=1):
        opts = _fetch_all_airport_pair_options(leg_spec, request, provider)
        if not opts:
            return None
        best_mid = min(opts, key=lambda o: _leg_generalized_cost(o, request, use_rt_half_fare=False))
        middle_legs.append(best_mid)
        base_fare = round(best_mid.one_way_base_fare_usd, 2)
        bag_fee = _compute_baggage_fee(best_mid, request)
        middle_tickets.append(
            BookedTicket(
                ticket_id=f"{schedule.schedule_id}-oj-reg-{offset}",
                ticket_type=TicketType.ONE_WAY,
                label=f"Ticket #{offset + 1}: Regional One-Way ({best_mid.origin} → {best_mid.destination})",
                airline_or_alliance=f"{best_mid.airline_name} ({best_mid.alliance})",
                cabin_summary=best_mid.cabin.value.replace("_", " ").title(),
                legs=[best_mid],
                leg_indices=[offset],
                base_fare_usd=base_fare,
                baggage_fees_usd=bag_fee,
                total_ticket_usd=round(base_fare + bag_fee, 2),
                pricing_note="Separate regional flight in its own cabin class (avoids up-faring to long-haul cabin).",
                booking_query_summary=(
                    f"Book One-Way: {best_mid.origin} → {best_mid.destination} on {best_mid.departure_date.isoformat()} "
                    f"({best_mid.airline_name}, {best_mid.cabin.value.replace('_', ' ').title()})"
                ),
            )
        )

    # Now evaluate pairing Leg 0 + Leg N-1 as an Open-Jaw / Round-Trip on a shared alliance or carrier
    first_options = _fetch_all_airport_pair_options(first_spec, request, provider)
    last_options = _fetch_all_airport_pair_options(last_spec, request, provider)

    best_itin: EvaluatedItinerary | None = None

    for alliance, (f_alliance, l_alliance) in _candidate_carrier_groups([first_options, last_options]):
        best_f = min(f_alliance, key=lambda o: _leg_generalized_cost(o, request, use_rt_half_fare=True))
        best_l = min(l_alliance, key=lambda o: _leg_generalized_cost(o, request, use_rt_half_fare=True))

        is_exact_rt = best_f.origin == best_l.destination and best_f.destination == best_l.origin
        t_type = TicketType.ROUND_TRIP if is_exact_rt else TicketType.OPEN_JAW
        t_type_name = "Round-Trip" if is_exact_rt else "Open-Jaw"

        anchor_base = provider.quote_multi_slice_ticket([best_f, best_l], t_type)
        anchor_bags = round(_compute_baggage_fee(best_f, request) + _compute_baggage_fee(best_l, request), 2)
        cabins_str = (
            best_f.cabin.value.replace("_", " ").title()
            if best_f.cabin == best_l.cabin
            else f"{best_f.cabin.value.title()} / {best_l.cabin.value.title()}"
        )
        anchor_ticket = BookedTicket(
            ticket_id=f"{schedule.schedule_id}-anchor-{_slug(alliance)}",
            ticket_type=t_type,
            label=f"Ticket #1: Anchor {t_type_name} ({best_f.origin} → {best_f.destination} / {best_l.origin} → {best_l.destination})",
            airline_or_alliance=alliance,
            cabin_summary=cabins_str,
            legs=[best_f, best_l],
            leg_indices=[0, len(schedule.legs) - 1],
            base_fare_usd=anchor_base,
            baggage_fees_usd=anchor_bags,
            total_ticket_usd=round(anchor_base + anchor_bags, 2),
            pricing_note=(
                f"Combines outbound ({best_f.origin}→{best_f.destination}) and return ({best_l.origin}→{best_l.destination}) "
                f"onto one {alliance} {t_type_name} ticket, eliminating one-way long-haul surcharges."
            ),
            booking_query_summary=(
                f"Book {t_type_name} (Multi-City 2-slice): Slice 1 {best_f.origin}→{best_f.destination} ({best_f.departure_date.isoformat()}), "
                f"Slice 2 {best_l.origin}→{best_l.destination} ({best_l.departure_date.isoformat()})"
            ),
        )

        all_legs = [best_f, *middle_legs, best_l]
        all_tickets = [anchor_ticket, *middle_tickets]

        bullets = [
            f"Anchor {t_type_name} ticket on {alliance} pairs your outbound ({best_f.origin}→{best_f.destination}) and return ({best_l.origin}→{best_l.destination}) to unlock Round-Trip fare buckets.",
            f"Regional hops ({len(middle_tickets)} flight{'s' if len(middle_tickets) != 1 else ''}) are booked separately so you can fly LCCs or Economy short-haul while keeping {cabins_str} on long-haul.",
            "Zero unprotected self-transfers: every separate ticket begins after a multi-day stay in a destination city.",
        ]

        itin = _assemble_itinerary(
            itinerary_id=f"{schedule.schedule_id}-oj-{_slug(alliance)}",
            strategy=StrategyKind.OPEN_JAW_PLUS_REGIONAL,
            strategy_label=f"Anchor {t_type_name} + {len(middle_tickets)} Regional One-Way{'s' if len(middle_tickets) != 1 else ''}",
            strategy_description="Pairs long-haul outbound & return onto one Open-Jaw/Round-Trip ticket, with separate regional hops.",
            schedule=schedule,
            legs=all_legs,
            tickets=all_tickets,
            request=request,
            explanation_bullets=bullets,
        )
        if best_itin is None or itin.effective_score < best_itin.effective_score:
            best_itin = itin

    return best_itin


def evaluate_nested_round_trips(
    schedule: CandidateSchedule,
    request: TripRequest,
    provider: FlightSearchProvider,
) -> EvaluatedItinerary | None:
    """Strategy 4: Anchor Round-Trip between Origin and Stop 1's hub, plus a nested regional
    Open-Jaw/Multi-City ticket covering the inner stops.
    """
    if len(schedule.legs) < 3:
        return None

    first_spec = schedule.legs[0]
    last_spec = schedule.legs[-1]
    inner_specs = schedule.legs[1:-1]

    first_options = _fetch_all_airport_pair_options(first_spec, request, provider)
    last_options = _fetch_all_airport_pair_options(last_spec, request, provider)
    inner_options_by_spec = [_fetch_all_airport_pair_options(spec, request, provider) for spec in inner_specs]
    if any(not opts for opts in inner_options_by_spec):
        return None

    best_itin: EvaluatedItinerary | None = None
    outer_groups = _candidate_carrier_groups([first_options, last_options])
    inner_groups = _candidate_carrier_groups(inner_options_by_spec)

    for outer_alliance, (f_opts, l_opts) in outer_groups:
        best_f = min(f_opts, key=lambda o: _leg_generalized_cost(o, request, use_rt_half_fare=True))
        best_l = min(l_opts, key=lambda o: _leg_generalized_cost(o, request, use_rt_half_fare=True))
        is_exact_rt = best_f.origin == best_l.destination and best_f.destination == best_l.origin
        outer_t_type = TicketType.ROUND_TRIP if is_exact_rt else TicketType.OPEN_JAW
        outer_cabins_str = (
            best_f.cabin.value.replace("_", " ").title()
            if best_f.cabin == best_l.cabin
            else f"{best_f.cabin.value.title()} / {best_l.cabin.value.title()}"
        )

        # Inner regional legs bundled on a regional alliance/carrier Open-Jaw / Multi-City ticket
        for inner_alliance, inner_per_slice in inner_groups:
            inner_chosen = [
                min(al_opts, key=lambda o: _leg_generalized_cost(o, request, use_rt_half_fare=True))
                for al_opts in inner_per_slice
            ]
            if not inner_chosen:
                continue

            outer_base = provider.quote_multi_slice_ticket([best_f, best_l], outer_t_type)
            outer_bags = round(_compute_baggage_fee(best_f, request) + _compute_baggage_fee(best_l, request), 2)
            outer_ticket = BookedTicket(
                ticket_id=f"{schedule.schedule_id}-nested-outer-{_slug(outer_alliance)}",
                ticket_type=outer_t_type,
                label=f"Ticket #1: Outer Long-Haul Ticket ({outer_alliance})",
                airline_or_alliance=outer_alliance,
                cabin_summary=outer_cabins_str,
                legs=[best_f, best_l],
                leg_indices=[0, len(schedule.legs) - 1],
                base_fare_usd=outer_base,
                baggage_fees_usd=outer_bags,
                total_ticket_usd=round(outer_base + outer_bags, 2),
                pricing_note=f"Outer {outer_alliance} ticket covering intercontinental outbound & return.",
                booking_query_summary=(
                    f"Book Outer Ticket: {best_f.origin}→{best_f.destination} ({best_f.departure_date.isoformat()}) "
                    f"& {best_l.origin}→{best_l.destination} ({best_l.departure_date.isoformat()})"
                ),
            )

            inner_t_type = TicketType.MULTI_CITY if len(inner_chosen) > 1 else TicketType.ONE_WAY
            inner_base = round(provider.quote_multi_slice_ticket(inner_chosen, inner_t_type) * 0.94, 2)
            inner_bags = round(sum(_compute_baggage_fee(leg, request) * 0.85 for leg in inner_chosen), 2)
            inner_cabins = highest_cabin([leg.cabin for leg in inner_chosen])
            inner_ticket = BookedTicket(
                ticket_id=f"{schedule.schedule_id}-nested-inner-{_slug(inner_alliance)}",
                ticket_type=inner_t_type,
                label=f"Ticket #2: Nested Regional Ticket ({inner_alliance})",
                airline_or_alliance=inner_alliance,
                cabin_summary=inner_cabins.value.replace("_", " ").title(),
                legs=inner_chosen,
                leg_indices=list(range(1, len(schedule.legs) - 1)),
                base_fare_usd=inner_base,
                baggage_fees_usd=inner_bags,
                total_ticket_usd=round(inner_base + inner_bags, 2),
                pricing_note=f"Nested {inner_alliance} regional multi-stop ticket in {inner_cabins.value.replace('_', ' ').title()}.",
                booking_query_summary="Book Inner Regional Ticket: "
                + ", ".join(
                    f"{leg.origin}→{leg.destination} ({leg.departure_date.isoformat()})" for leg in inner_chosen
                ),
            )

            all_legs = [best_f, *inner_chosen, best_l]
            itin = _assemble_itinerary(
                itinerary_id=f"{schedule.schedule_id}-nested-{_slug(outer_alliance)}-{_slug(inner_alliance)}",
                strategy=StrategyKind.NESTED_ROUND_TRIPS,
                strategy_label="2 Nested Multi-Stop Tickets (Outer + Inner)",
                strategy_description="2 tickets total: 1 outer long-haul ticket + 1 nested regional multi-city ticket.",
                schedule=schedule,
                legs=all_legs,
                tickets=[outer_ticket, inner_ticket],
                request=request,
                explanation_bullets=[
                    f"Splits the trip into just 2 tickets: an outer {outer_alliance} long-haul ticket and an inner {inner_alliance} regional ticket.",
                    "Decouples long-haul Business/Premium cabin rules from regional Economy segments while keeping ticket count to 2.",
                ],
            )
            if best_itin is None or itin.effective_score < best_itin.effective_score:
                best_itin = itin

    return best_itin


def evaluate_hub_split_strategy(
    schedule: CandidateSchedule,
    request: TripRequest,
    provider: FlightSearchProvider,
) -> EvaluatedItinerary | None:
    """Strategy 5: Delegate intermediate hub-splitting evaluation to hub_splitter module."""
    return evaluate_hub_split_candidates(
        schedule=schedule,
        request=request,
        provider=provider,
        compute_baggage_fee=_compute_baggage_fee,
        leg_generalized_cost=_leg_generalized_cost,
        fetch_pair_options=_fetch_all_airport_pair_options,
        assemble_itinerary=_assemble_itinerary,
    )


def evaluate_all_partitions_for_schedule(
    schedule: CandidateSchedule,
    request: TripRequest,
    provider: FlightSearchProvider,
    on_strategy_start: Callable[[str], None] | None = None,
    on_strategy_done: Callable[[str], None] | None = None,
) -> list[EvaluatedItinerary]:
    """Evaluate all ticket partitioning strategies on a candidate schedule and compute relative savings."""
    results: list[EvaluatedItinerary] = []

    strategy_runners: list[
        tuple[str, Callable[[CandidateSchedule, TripRequest, FlightSearchProvider], EvaluatedItinerary | None]]
    ] = [
        ("1 Single Multi-City Ticket", evaluate_single_multi_city_ticket),
        ("Separate One-Way Tickets", evaluate_all_one_ways),
        ("Anchor Open-Jaw + Regional Hops", evaluate_open_jaw_plus_regional),
        ("Nested Multi-Stop Tickets", evaluate_nested_round_trips),
        ("Intermediate Hub-Split", evaluate_hub_split_strategy),
    ]

    single: EvaluatedItinerary | None = None
    one_ways: EvaluatedItinerary | None = None

    for label, runner in strategy_runners:
        if on_strategy_start is not None:
            on_strategy_start(label)
        itin = runner(schedule, request, provider)
        if itin:
            results.append(itin)
            if itin.strategy == StrategyKind.SINGLE_TICKET:
                single = itin
            elif itin.strategy == StrategyKind.ALL_ONE_WAYS:
                one_ways = itin
        if on_strategy_done is not None:
            on_strategy_done(label)

    # Compute savings deltas vs Single Multi-City Ticket and vs All One-Ways
    single_price = single.total_price_usd if single else None
    ow_price = one_ways.total_price_usd if one_ways else None

    for itin in results:
        if single_price is not None:
            itin.savings_vs_single_ticket_usd = round(single_price - itin.total_price_usd, 2)
        if ow_price is not None:
            itin.savings_vs_all_one_ways_usd = round(ow_price - itin.total_price_usd, 2)

    return results
