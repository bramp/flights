"""Multi-objective generalized cost scoring, dominance checking, and Pareto frontier selection."""

from __future__ import annotations

from backend.app.models.schemas import (
    EvaluatedItinerary,
    OptimizationWeights,
    StrategyKind,
)


def compute_effective_score(
    total_price_usd: float,
    total_travel_hours: float,
    protected_transfers: int,
    self_transfers: int,
    tickets_count: int,
    weights: OptimizationWeights,
) -> float:
    """Compute the generalized cost score combining monetary fare, time value, and transfer risk."""
    extra_tickets = max(0, tickets_count - 1)
    return round(
        total_price_usd
        + (total_travel_hours * weights.value_of_time_per_hour)
        + (protected_transfers * weights.protected_transfer_penalty)
        + (self_transfers * weights.self_transfer_penalty)
        + (extra_tickets * weights.separate_ticket_penalty),
        2,
    )


def is_dominated(candidate: EvaluatedItinerary, other: EvaluatedItinerary) -> bool:
    """Return True if `other` Pareto-dominates `candidate` across:
    (total_price_usd, total_travel_hours, weighted_transfers, self_transfers).
    """
    cand_transfers = candidate.protected_transfers + (candidate.self_transfers * 2)
    other_transfers = other.protected_transfers + (other.self_transfers * 2)

    no_worse = (
        other.total_price_usd <= candidate.total_price_usd
        and other.total_travel_hours <= candidate.total_travel_hours
        and other_transfers <= cand_transfers
        and other.self_transfers <= candidate.self_transfers
    )
    strictly_better = (
        other.total_price_usd < candidate.total_price_usd
        or other.total_travel_hours < candidate.total_travel_hours
        or other_transfers < cand_transfers
        or other.self_transfers < candidate.self_transfers
    )
    return no_worse and strictly_better


def extract_pareto_frontier(itineraries: list[EvaluatedItinerary]) -> list[EvaluatedItinerary]:
    """Return non-dominated itineraries sorted by effective_score."""
    frontier = [
        cand
        for cand in itineraries
        if not any(is_dominated(cand, other) for other in itineraries if other.itinerary_id != cand.itinerary_id)
    ]
    frontier.sort(key=lambda i: i.effective_score)
    return frontier


def annotate_badges(itineraries: list[EvaluatedItinerary]) -> None:
    """Assign comparison badges (Best Overall, Cheapest, Fastest, Best Single Ticket)."""
    if not itineraries:
        return

    for itin in itineraries:
        itin.badges = []

    best_score = min(itineraries, key=lambda i: i.effective_score)
    best_score.badges.append("Best Overall Balance")

    cheapest = min(itineraries, key=lambda i: i.total_price_usd)
    if "Cheapest Total Price" not in cheapest.badges:
        cheapest.badges.append("Cheapest Total Price")

    fastest = min(
        itineraries,
        key=lambda i: (i.total_travel_hours, i.protected_transfers + i.self_transfers),
    )
    if "Fastest Travel Time" not in fastest.badges:
        fastest.badges.append("Fastest Travel Time")

    single_tickets = [i for i in itineraries if i.strategy == StrategyKind.SINGLE_TICKET]
    if single_tickets:
        best_single = min(single_tickets, key=lambda i: i.effective_score)
        best_single.badges.append("Best Single Ticket (1 PNR)")
