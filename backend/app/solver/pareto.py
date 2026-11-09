"""Score candidate itineraries and compare their Pareto frontier."""

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
    """Compute the generalized cost of an itinerary in USD.

    Add the total price, weighted travel hours, protected and self-transfer
    penalties, and a penalty for each ticket after the first. Round the
    resulting score to two decimal places. Lower scores are preferred.

    Args:
        total_price_usd: Base fares and estimated baggage fees.
        total_travel_hours: Flight, layover, and assumed self-transfer time.
        protected_transfers: Number of within-leg stops.
        self_transfers: Number of separately ticketed hub connections.
        tickets_count: Number of proposed tickets.
        weights: USD-valued time, transfer, and extra-ticket penalties.

    Returns:
        The rounded generalized cost score, not a verified ticket price.

    Examples:
        >>> from backend.app.models.schemas import OptimizationWeights
        >>> from backend.app.solver.pareto import compute_effective_score
        >>> weights = OptimizationWeights(
        ...     value_of_time_per_hour=10, protected_transfer_penalty=5,
        ...     self_transfer_penalty=30, separate_ticket_penalty=20,
        ... )
        >>> compute_effective_score(100, 2, 1, 1, 2, weights)
        175.0
    """
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
    """Return whether another itinerary Pareto-dominates the candidate.

    Compare total price, travel hours, weighted transfers, and self-transfers.
    Weighted transfers count each protected transfer once and each
    self-transfer twice. The other itinerary must be no worse in all four
    measures and strictly better in at least one. Effective score is not
    itself a dominance measure.
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
    """Return non-dominated itineraries sorted by effective score.

    Comparisons are limited to the supplied candidates. Entries with the
    same itinerary ID are not compared against one another. The returned list
    contains the original itinerary objects and does not reorder the input.
    """
    frontier = [
        cand
        for cand in itineraries
        if not any(is_dominated(cand, other) for other in itineraries if other.itinerary_id != cand.itinerary_id)
    ]
    frontier.sort(key=lambda i: i.effective_score)
    return frontier


def annotate_badges(itineraries: list[EvaluatedItinerary]) -> None:
    """Replace comparison badges on the supplied itinerary objects.

    Mark the best score, lowest price, fastest travel time, and best-scoring
    single-ticket strategy when present. Fastest-time ties prefer fewer total
    transfers; remaining ties use the first matching input. An itinerary can
    receive more than one badge.
    """
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
