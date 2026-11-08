"""Normalized requests for flight discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption


@dataclass(frozen=True)
class LegSearch:
    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    departure_date: date
    cabin: ConcreteCabinClass

    def __post_init__(self) -> None:
        origins = tuple(dict.fromkeys(code.strip().upper() for code in self.origins if code.strip()))
        destinations = tuple(dict.fromkeys(code.strip().upper() for code in self.destinations if code.strip()))
        if not origins or not destinations:
            raise ValueError("A flight search requires at least one origin and destination airport.")
        object.__setattr__(self, "origins", origins)
        object.__setattr__(self, "destinations", destinations)

    @classmethod
    def single(cls, origin: str, destination: str, departure_date: date, cabin: ConcreteCabinClass) -> LegSearch:
        return cls((origin,), (destination,), departure_date, cabin)


class SearchStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class SearchIssueKind(StrEnum):
    PROVIDER_ERROR = "provider_error"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MISSING_CREDENTIALS = "missing_credentials"
    TRUNCATED = "truncated"


@dataclass(frozen=True)
class SearchIssue:
    kind: SearchIssueKind
    message: str


@dataclass(frozen=True)
class SearchResult:
    options: tuple[FlightLegOption, ...] = ()
    status: SearchStatus = SearchStatus.COMPLETE
    issues: tuple[SearchIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.status != SearchStatus.COMPLETE and not self.issues:
            raise ValueError("An incomplete flight search must report an issue.")
        if self.status == SearchStatus.FAILED and self.options:
            raise ValueError("A failed flight search cannot contain options.")
