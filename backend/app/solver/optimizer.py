"""End-to-end multi-city optimization orchestrator and Pareto frontier extractor."""

from __future__ import annotations

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.schemas import (
    EvaluatedItinerary,
    OptimizationResponse,
    ProviderMode,
    StrategyKind,
    TripRequest,
)
from backend.app.providers.base import CachedFlightProvider, FlightSearchProvider
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.solver.cabin import resolve_leg_max_stops
from backend.app.solver.pareto import (
    annotate_badges,
    extract_pareto_frontier,
    is_dominated,
)
from backend.app.solver.partitioner import evaluate_all_partitions_for_schedule
from backend.app.solver.route_dag import generate_candidate_schedules

__all__ = [
    "annotate_badges",
    "extract_pareto_frontier",
    "is_dominated",
    "optimize_trip",
]


def optimize_trip(
    request: TripRequest,
    raw_provider: FlightSearchProvider,
    cache: FlightCache,
) -> OptimizationResponse:
    """Run schedule DAG generation, cached flight search, ticket partitioning, and Pareto ranking."""
    cache.reset_session_counters()
    if isinstance(raw_provider, CompositeFlightProvider):
        raw_provider.configure_for_run(
            cache=cache,
            mode=request.provider_mode,
            max_api_calls=request.max_api_calls_per_run,
        )

    cached_provider = CachedFlightProvider(
        delegate=raw_provider,
        cache=cache,
        force_refresh=request.force_refresh,
    )

    warnings: list[str] = []
    if request.provider_mode == ProviderMode.OFFLINE:
        warnings.append("TESTING: All flights and fares shown are simulated, not bookable, and are never cached.")
    total_window_days = (request.latest_return - request.earliest_departure).days
    min_req_nights = sum(s.min_nights for s in request.stops)
    if total_window_days < min_req_nights:
        warnings.append(
            f"Trip window ({total_window_days} days) is shorter than sum of minimum nights ({min_req_nights} nights); "
            "stay durations were proportionally compressed."
        )

    max_sched = 4 if request.provider_mode in (ProviderMode.SERPAPI, ProviderMode.FAST_FLIGHTS) else 8
    schedules = generate_candidate_schedules(request, max_schedules=max_sched)
    if any(s.schedule_id.startswith("sched-fallback") for s in schedules):
        warnings.append(
            "Individual stop date windows did not overlap cleanly with stay durations; "
            "showing the closest feasible schedule within your trip window."
        )

    all_evaluated: list[EvaluatedItinerary] = []

    for sched in schedules:
        partitions = evaluate_all_partitions_for_schedule(sched, request, cached_provider)
        all_evaluated.extend(partitions)

    if isinstance(raw_provider, CompositeFlightProvider) and raw_provider.warnings:
        warnings.extend(raw_provider.warnings)

    if not all_evaluated:
        raise ValueError(
            "No valid flight combinations found for the requested stops and dates "
            "(check distinct airports, live provider availability, and query limits). "
            + " ".join(dict.fromkeys(warnings))
        )

    all_evaluated.sort(key=lambda i: i.effective_score)
    annotate_badges(all_evaluated)

    pareto = extract_pareto_frontier(all_evaluated)

    # Build a best-of-each-strategy comparison table so the user can directly compare:
    # 1 Single Ticket vs Open-Jaw+One-Ways vs Nested Tickets vs All One-Ways vs Hub-Split
    best_by_strategy: dict[StrategyKind, EvaluatedItinerary] = {}
    for itin in all_evaluated:
        if itin.strategy not in best_by_strategy:
            best_by_strategy[itin.strategy] = itin

    strategy_comparison = sorted(best_by_strategy.values(), key=lambda i: i.effective_score)

    # Recompute cross-strategy baseline deltas on the comparison set
    baseline_single = best_by_strategy.get(StrategyKind.SINGLE_TICKET)
    baseline_ow = best_by_strategy.get(StrategyKind.ALL_ONE_WAYS)
    for itin in all_evaluated:
        if baseline_single:
            itin.savings_vs_single_ticket_usd = round(baseline_single.total_price_usd - itin.total_price_usd, 2)
        if baseline_ow:
            itin.savings_vs_all_one_ways_usd = round(baseline_ow.total_price_usd - itin.total_price_usd, 2)

    recommended = all_evaluated[0]
    if recommended.strategy != StrategyKind.HUB_SPLIT and len(recommended.legs) == len(recommended.stop_visits) + 1:
        stops_by_id = {s.id: s for s in request.stops}
        for idx, leg in enumerate(recommended.legs):
            if idx < len(recommended.stop_visits):
                stop_spec = stops_by_id.get(recommended.stop_visits[idx].stop_id)
                req_stops = stop_spec.outbound_stops if stop_spec else request.return_leg_stops
            else:
                req_stops = request.return_leg_stops
            target_max = resolve_leg_max_stops(leg.origin, leg.destination, req_stops, request.stops_policy)
            if target_max is not None and leg.stops_count > target_max:
                limit_label = "nonstop" if target_max == 0 else f"≤{target_max} stop"
                warnings.append(
                    f"No {limit_label} flight was available for {leg.origin}→{leg.destination} on "
                    f"{leg.departure_date.isoformat()}; relaxed to {leg.stops_count} stop(s)."
                )

    return OptimizationResponse(
        recommended=recommended,
        pareto_frontier=pareto[:8],
        strategy_comparison=strategy_comparison,
        schedules_evaluated=len(schedules),
        ticket_partitions_evaluated=len(all_evaluated),
        cache_stats=cache.get_stats(),
        warnings=warnings,
    )
