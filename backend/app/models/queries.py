"""Normalized requests for flight discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from backend.app.models.schemas import ConcreteCabinClass


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
