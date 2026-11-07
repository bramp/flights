"""Airport directory, coordinates, metro area groupings, and transit hub corridors."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AirportInfo:
    code: str
    name: str
    city: str
    country: str
    region: str  # NA, EU, ASIA, ME, OC, SA, INTL
    lat: float
    lon: float
    metro_code: str
    is_major_hub: bool = False
    nearby_codes: tuple[str, ...] = ()
    has_coordinates: bool = True


def _load_airports() -> dict[str, AirportInfo]:
    records = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    airports: dict[str, AirportInfo] = {}
    for record in records:
        record["nearby_codes"] = tuple(record.get("nearby_codes", ()))
        airport = AirportInfo(**record)
        if airport.code in airports:
            raise ValueError(f"Duplicate airport code: {airport.code}")
        airports[airport.code] = airport
    return airports


AIRPORTS: dict[str, AirportInfo] = _load_airports()

# Dynamically populated from live Google Flights search responses and cached flight segments
DISCOVERED_AIRPORTS: dict[str, AirportInfo] = {}
OBSERVED_PAIR_HOURS: dict[tuple[str, str], float] = {}


def _build_metro_groups(airports: dict[str, AirportInfo]) -> dict[str, dict[str, object]]:
    by_metro: dict[str, list[AirportInfo]] = {}
    for info in airports.values():
        by_metro.setdefault(info.metro_code, []).append(info)
    groups: dict[str, dict[str, object]] = {}
    for m_code, members in by_metro.items():
        if len(members) < 2 and not members[0].is_major_hub:
            continue
        primary = next((m for m in members if m.code == m_code), None) or next(
            (m for m in members if m.is_major_hub), members[0]
        )
        label = primary.city.split("/")[0].strip()
        groups[label] = {
            "codes": [m.code for m in members],
            "primary": primary.code,
            "subtitle": f"{label} ({primary.country})",
        }
    return groups


METRO_GROUPS: dict[str, dict[str, object]] = _build_metro_groups(AIRPORTS)


def register_discovered_airport(code: str, name: str = "", city: str = "") -> None:
    """Register airport metadata extracted directly from a flight search response."""
    upper = code.strip().upper()
    if len(upper) != 3 or upper in AIRPORTS:
        return
    clean_name = name.strip() or f"{upper} Airport"
    inferred_city = city.strip()
    if not inferred_city:
        # Extract city prefix if airport name is e.g. "Heraklion International Airport"
        for suffix in (" International Airport", " Airport", " National Airport"):
            if clean_name.endswith(suffix) and len(clean_name) > len(suffix):
                inferred_city = clean_name[: -len(suffix)].split("(")[0].split('"')[0].strip()
                break
    existing = DISCOVERED_AIRPORTS.get(upper)
    if existing and existing.name != f"{upper} Airport" and clean_name == f"{upper} Airport":
        return
    DISCOVERED_AIRPORTS[upper] = AirportInfo(
        code=upper,
        name=clean_name,
        city=inferred_city or upper,
        country="INTL",
        region="INTL",
        lat=0.0,
        lon=0.0,
        metro_code=upper,
        is_major_hub=False,
        nearby_codes=(),
        has_coordinates=False,
    )


def record_observed_duration(origin: str, destination: str, duration_hours: float) -> None:
    """Record actual flight block duration observed from flight search results."""
    orig = origin.strip().upper()
    dest = destination.strip().upper()
    if len(orig) != 3 or len(dest) != 3 or orig == dest or duration_hours <= 0:
        return
    pair = (orig, dest)
    prev = OBSERVED_PAIR_HOURS.get(pair)
    if prev is None or duration_hours < prev:
        OBSERVED_PAIR_HOURS[pair] = round(duration_hours, 2)
    rev_pair = (dest, orig)
    if rev_pair not in OBSERVED_PAIR_HOURS:
        OBSERVED_PAIR_HOURS[rev_pair] = round(duration_hours, 2)


def all_known_airports() -> dict[str, AirportInfo]:
    """Return catalog airports merged with airports discovered during flight searches."""
    return {**DISCOVERED_AIRPORTS, **AIRPORTS}


def get_airport(code: str) -> AirportInfo:
    """Return airport metadata from catalog or flight search discovery without inventing coordinates."""
    upper = code.strip().upper()
    if upper in AIRPORTS:
        return AIRPORTS[upper]
    if upper in DISCOVERED_AIRPORTS:
        return DISCOVERED_AIRPORTS[upper]
    return AirportInfo(
        code=upper,
        name=f"{upper} Airport",
        city=upper,
        country="INTL",
        region="INTL",
        lat=0.0,
        lon=0.0,
        metro_code=upper,
        is_major_hub=False,
        nearby_codes=(),
        has_coordinates=False,
    )


def haversine_km(code_a: str, code_b: str) -> float:
    """Compute great-circle distance in kilometers between two airport codes,
    falling back to observed flight duration if coordinates are unknown.
    """
    orig = code_a.strip().upper()
    dest = code_b.strip().upper()
    if orig == dest:
        return 0.0
    a = get_airport(orig)
    b = get_airport(dest)
    if not a.has_coordinates or not b.has_coordinates:
        obs_hrs = OBSERVED_PAIR_HOURS.get((orig, dest))
        if obs_hrs is not None:
            return round(max(80.0, (obs_hrs - 0.5) * 800.0), 1)
        return 0.0
    r = 6371.0
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(hav)))


def estimate_nonstop_hours(code_a: str, code_b: str) -> float:
    """Estimate block time in hours between two airports, preferring observed flight search durations."""
    orig = code_a.strip().upper()
    dest = code_b.strip().upper()
    if orig == dest:
        return 0.0
    obs_hrs = OBSERVED_PAIR_HOURS.get((orig, dest))
    if obs_hrs is not None:
        return obs_hrs
    a = get_airport(orig)
    b = get_airport(dest)
    if not a.has_coordinates or not b.has_coordinates:
        # Safe neutral fallback when coordinates are missing and route hasn't been searched yet
        return 3.5
    dist_km = haversine_km(orig, dest)
    if dist_km <= 0:
        return 0.0
    # Cruise ~830 km/h + 0.65h taxi/climb/approach
    return round((dist_km / 830.0) + 0.65, 2)


def same_metro_area(code_a: str, code_b: str) -> bool:
    """Return True if two airports belong to the same metropolitan area."""
    if code_a.upper() == code_b.upper():
        return True
    return get_airport(code_a).metro_code == get_airport(code_b).metro_code


def suggest_airports(query: str) -> list[dict[str, object]]:
    """Search cities/airports and return matching airports plus nearby alternatives."""
    q = query.strip().lower()
    results: list[dict[str, object]] = []
    seen: set[str] = set()
    known = all_known_airports()

    for info in known.values():
        if (
            not q
            or q in info.code.lower()
            or q in info.city.lower()
            or q in info.name.lower()
            or q in info.metro_code.lower()
        ):
            if info.code in seen:
                continue
            seen.add(info.code)
            nearby_details: list[dict[str, object]] = [
                {
                    "code": nb,
                    "name": known[nb].name,
                    "city": known[nb].city,
                    "same_metro": known[nb].metro_code == info.metro_code,
                }
                for nb in info.nearby_codes
                if nb in known
            ]
            results.append(
                {
                    "code": info.code,
                    "name": info.name,
                    "city": info.city,
                    "country": info.country,
                    "region": info.region,
                    "metro_code": info.metro_code,
                    "is_major_hub": info.is_major_hub,
                    "nearby": nearby_details,
                }
            )
    return results[:20]


def candidate_intermediate_hubs(origin: str, destination: str, max_hubs: int = 3) -> list[str]:
    """Find geographically sensible major transit hubs between origin and destination."""
    orig_info = get_airport(origin)
    dest_info = get_airport(destination)
    if not orig_info.has_coordinates or not dest_info.has_coordinates:
        return []
    direct_km = haversine_km(origin, destination)

    # Only split legs that are medium/long haul (>= 2,200 km)
    if direct_km < 2200:
        return []

    scored_hubs: list[tuple[float, str]] = []
    for code, hub in AIRPORTS.items():
        if not hub.is_major_hub:
            continue
        if hub.metro_code in (orig_info.metro_code, dest_info.metro_code):
            continue
        d1 = haversine_km(origin, code)
        d2 = haversine_km(code, destination)
        # Each sub-leg should be meaningful (> 500 km) and total detour <= 38%
        if d1 < 500 or d2 < 500:
            continue
        detour_ratio = (d1 + d2) / max(direct_km, 1.0)
        if detour_ratio <= 1.38:
            scored_hubs.append((detour_ratio, code))

    scored_hubs.sort(key=lambda item: item[0])
    return [code for _, code in scored_hubs[:max_hubs]]
