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
    region: str  # NA, EU, ASIA, ME, OC, SA
    lat: float
    lon: float
    metro_code: str
    is_major_hub: bool = False
    nearby_codes: tuple[str, ...] = ()


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


COUNTRY_NAMES: dict[str, str] = {
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "FR": "France",
    "NL": "Netherlands",
    "BE": "Belgium",
    "DE": "Germany",
    "CH": "Switzerland",
    "AT": "Austria",
    "SK": "Slovakia",
    "CZ": "Czechia",
    "HU": "Hungary",
    "IT": "Italy",
    "ES": "Spain",
    "PT": "Portugal",
    "GR": "Greece",
    "DK": "Denmark",
    "SE": "Sweden",
    "FI": "Finland",
    "IE": "Ireland",
    "TR": "Turkey",
    "AE": "United Arab Emirates",
    "QA": "Qatar",
    "JP": "Japan",
    "KR": "South Korea",
    "TW": "Taiwan",
    "HK": "Hong Kong",
    "MO": "Macau",
    "SG": "Singapore",
    "MY": "Malaysia",
    "TH": "Thailand",
    "PH": "Philippines",
    "IN": "India",
    "AU": "Australia",
    "NZ": "New Zealand",
}

CITY_DISTANCE_MI: dict[str, int] = {
    "SFO": 13,
    "OAK": 12,
    "SJC": 34,
    "LAX": 11,
    "BUR": 12,
    "SNA": 35,
    "ONT": 38,
    "JFK": 15,
    "EWR": 11,
    "LGA": 8,
    "LHR": 14,
    "STN": 30,
    "LGW": 25,
    "LTN": 27,
    "LCY": 7,
    "SEN": 35,
    "CDG": 16,
    "ORY": 9,
    "BVA": 43,
    "FCO": 16,
    "CIA": 9,
    "MXP": 25,
    "LIN": 5,
    "BGY": 28,
    "AMS": 9,
    "RTM": 35,
    "EIN": 66,
    "ATH": 12,
    "HND": 9,
    "NRT": 37,
    "KIX": 24,
    "ITM": 9,
    "ICN": 30,
    "GMP": 10,
    "TPE": 19,
    "TSA": 3,
    "BKK": 16,
    "DMK": 13,
}

METRO_GROUPS: dict[str, dict[str, object]] = {
    "San Francisco": {"codes": ["SFO", "OAK", "SJC"], "primary": "SFO", "subtitle": "Bay Area, United States"},
    "Los Angeles": {
        "codes": ["LAX", "BUR", "SNA", "ONT"],
        "primary": "LAX",
        "subtitle": "Southern California, United States",
    },
    "New York": {"codes": ["JFK", "EWR", "LGA"], "primary": "JFK", "subtitle": "New York Metro, United States"},
    "Washington D.C.": {"codes": ["IAD", "DCA", "BWI"], "primary": "IAD", "subtitle": "Capital Region, United States"},
    "Chicago": {"codes": ["ORD", "MDW"], "primary": "ORD", "subtitle": "Illinois, United States"},
    "Miami": {"codes": ["MIA", "FLL"], "primary": "MIA", "subtitle": "South Florida, United States"},
    "London": {"codes": ["LHR", "STN", "LGW", "LTN", "LCY", "SEN"], "primary": "LHR", "subtitle": "Capital of England"},
    "Paris": {"codes": ["CDG", "ORY", "BVA"], "primary": "CDG", "subtitle": "Capital of France"},
    "Rome": {"codes": ["FCO", "CIA"], "primary": "FCO", "subtitle": "Capital of Italy"},
    "Milan": {"codes": ["MXP", "LIN", "BGY"], "primary": "MXP", "subtitle": "Lombardy, Italy"},
    "Amsterdam": {"codes": ["AMS", "RTM", "EIN"], "primary": "AMS", "subtitle": "Capital of the Netherlands"},
    "Brussels": {"codes": ["BRU", "CRL"], "primary": "BRU", "subtitle": "Capital of Belgium"},
    "Frankfurt": {"codes": ["FRA", "HHN"], "primary": "FRA", "subtitle": "Hesse, Germany"},
    "Athens": {"codes": ["ATH"], "primary": "ATH", "subtitle": "Capital of Greece"},
    "Istanbul": {"codes": ["IST", "SAW"], "primary": "IST", "subtitle": "Turkey"},
    "Dubai": {"codes": ["DXB", "AUH", "SHJ"], "primary": "DXB", "subtitle": "United Arab Emirates"},
    "Tokyo": {"codes": ["HND", "NRT"], "primary": "HND", "subtitle": "Capital of Japan"},
    "Osaka / Kyoto": {"codes": ["KIX", "ITM", "UKB"], "primary": "KIX", "subtitle": "Kansai Region, Japan"},
    "Seoul": {"codes": ["ICN", "GMP"], "primary": "ICN", "subtitle": "Capital of South Korea"},
    "Taipei": {"codes": ["TPE", "TSA"], "primary": "TPE", "subtitle": "Capital of Taiwan"},
    "Hong Kong": {"codes": ["HKG", "MFM"], "primary": "HKG", "subtitle": "Pearl River Delta"},
    "Bangkok": {"codes": ["BKK", "DMK"], "primary": "BKK", "subtitle": "Capital of Thailand"},
    "Singapore": {"codes": ["SIN"], "primary": "SIN", "subtitle": "Republic of Singapore"},
}


def get_airport(code: str) -> AirportInfo:
    """Return airport metadata, or synthesize a reasonable fallback for unknown codes."""
    upper = code.strip().upper()
    if upper in AIRPORTS:
        return AIRPORTS[upper]
    # Deterministic fallback coordinates based on code characters
    seed = sum(ord(ch) * (idx + 1) for idx, ch in enumerate(upper))
    lat = ((seed % 90) - 30) * 1.0
    lon = (((seed * 7) % 280) - 140) * 1.0
    return AirportInfo(
        code=upper,
        name=f"{upper} Airport",
        city=upper,
        country="INTL",
        region="EU" if lon > -20 and lon < 40 else ("ASIA" if lon >= 40 else "NA"),
        lat=lat,
        lon=lon,
        metro_code=upper,
        is_major_hub=False,
        nearby_codes=(),
    )


def haversine_km(code_a: str, code_b: str) -> float:
    """Compute great-circle distance in kilometers between two airport codes."""
    if code_a.upper() == code_b.upper():
        return 0.0
    a = get_airport(code_a)
    b = get_airport(code_b)
    r = 6371.0
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(hav)))


def estimate_nonstop_hours(code_a: str, code_b: str) -> float:
    """Estimate realistic block time in hours between two airports."""
    dist_km = haversine_km(code_a, code_b)
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

    for info in AIRPORTS.values():
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
            nearby_details = [
                {
                    "code": nb,
                    "name": AIRPORTS[nb].name,
                    "city": AIRPORTS[nb].city,
                    "same_metro": AIRPORTS[nb].metro_code == info.metro_code,
                }
                for nb in info.nearby_codes
                if nb in AIRPORTS
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
