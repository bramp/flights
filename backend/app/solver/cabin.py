"""Per-leg and duration-based cabin class resolver."""

from __future__ import annotations

from backend.app.data.airports import estimate_nonstop_hours
from backend.app.models.schemas import (
    CabinClass,
    CabinPolicy,
    ConcreteCabinClass,
)

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
