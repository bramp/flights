"""Airline directory loaded from ``airlines.json``.

Airline names, codes, alliance memberships, and bag fees are manually
maintained reference data and can become outdated. Bag fees are estimates in
USD and are not a verified fare policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MAJOR_ALLIANCES: tuple[str, ...] = ("Star Alliance", "Oneworld", "SkyTeam")
LCC = "LCC"
NON_ALIGNED = "Non-Aligned"
VALID_CLASSIFICATIONS: frozenset[str] = frozenset((*MAJOR_ALLIANCES, LCC, NON_ALIGNED))
AIRLINES_JSON_PATH = Path(__file__).with_suffix(".json")


@dataclass(frozen=True)
class AirlineInfo:
    """Describe an airline's static reference metadata.

    Attributes:
        code: Unique two-character IATA airline code.
        alliance: One of ``MAJOR_ALLIANCES``, ``"LCC"``, or ``"Non-Aligned"``.
        name: Display name, used to match carriers in live responses by name.
        bag_fee_usd: Estimated fee per checked bag in US dollars, if known.
    """

    code: str
    alliance: str
    name: str | None = None
    bag_fee_usd: float | None = None

    @property
    def is_lcc(self) -> bool:
        return self.alliance == LCC


def _load_airlines(path: Path = AIRLINES_JSON_PATH) -> dict[str, AirlineInfo]:
    records = json.loads(path.read_text(encoding="utf-8"))
    airlines: dict[str, AirlineInfo] = {}
    for record in records:
        airline = AirlineInfo(**record)
        if len(airline.code) != 2 or not airline.code.isalnum() or airline.code != airline.code.upper():
            raise ValueError(f"Invalid airline code: {airline.code!r}")
        if airline.code in airlines:
            raise ValueError(f"Duplicate airline code: {airline.code}")
        if airline.alliance not in VALID_CLASSIFICATIONS:
            raise ValueError(f"Unknown alliance {airline.alliance!r} for airline {airline.code}")
        airlines[airline.code] = airline
    missing = [alliance for alliance in MAJOR_ALLIANCES if not any(a.alliance == alliance for a in airlines.values())]
    if missing:
        raise ValueError(f"No airlines listed for alliances: {', '.join(missing)}")
    return airlines


AIRLINES: dict[str, AirlineInfo] = _load_airlines()
