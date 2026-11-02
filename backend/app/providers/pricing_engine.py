"""Realistic airline schedule, alliance, cabin, and non-linear fare engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from backend.app.data.airports import (
    estimate_nonstop_hours,
    get_airport,
    haversine_km,
)
from backend.app.models.schemas import (
    ConcreteCabinClass,
    FlightLegOption,
    FlightSegment,
)
from backend.app.providers.base import FlightSearchProvider


@dataclass(frozen=True)
class CarrierProfile:
    """Reference carrier metadata and synthetic fallback simulation parameters.

    NOTE ON DATA PROVENANCE & VALIDITY:
    - `code`, `name`, `alliance`, and `is_lcc`: Sourced from public IATA 2-letter airline
      designators and official Star Alliance / Oneworld / SkyTeam member rosters (accurate
      as of 2026). When using live Google Flights queries, Google returns the airline name/code
      and exact flight segments, so only `alliance`, `is_lcc`, and fallback baggage fee metadata
      are needed if the API response omits alliance/baggage details.
    - `regions`, `hubs`, and `price_factor`: Hand-authored approximations used ONLY by
      `RealisticPricingProvider` (the offline simulator/fallback) to synthesize plausible routes
      and prices when no live Google Flights provider is active. Live flight providers DO NOT
      use `regions`, `hubs`, or `price_factor` — actual routes, layover hubs, durations, and
      prices come directly from the Google Flights response.
    """

    code: str
    name: str
    alliance: str  # "Star Alliance", "Oneworld", "SkyTeam", "LCC"
    regions: tuple[str, ...]
    hubs: tuple[str, ...]
    is_lcc: bool
    price_factor: float
    bag_fee_usd: float


# Provenance:
# - IATA codes, carrier names, and alliance memberships (`Star Alliance`, `Oneworld`, `SkyTeam`, `LCC`)
#   reflect published airline alliance memberships and major global carrier hubs as of 2026.
# - `bag_fee_usd` reflects approximate standard 1st checked bag fees (USD) on basic/standard economy fares
#   as of 2025-2026 for fallback estimation when live fare brand baggage data is not returned.
# - `regions`, `hubs`, and `price_factor` are synthetic parameters used strictly for offline mock flight
#   generation in `RealisticPricingProvider` and should NOT be used when live Google Flights data is returned.
CARRIERS: tuple[CarrierProfile, ...] = (
    # Star Alliance
    CarrierProfile(
        "UA",
        "United Airlines",
        "Star Alliance",
        ("NA", "EU", "ASIA", "OC"),
        ("SFO", "LAX", "EWR", "ORD", "IAD"),
        False,
        1.02,
        40.0,
    ),
    CarrierProfile(
        "LH", "Lufthansa", "Star Alliance", ("EU", "NA", "ASIA", "ME"), ("FRA", "MUC", "ZRH", "VIE"), False, 1.04, 45.0
    ),
    CarrierProfile(
        "NH", "ANA (All Nippon)", "Star Alliance", ("ASIA", "NA", "EU"), ("HND", "NRT", "KIX"), False, 1.05, 35.0
    ),
    CarrierProfile(
        "SQ", "Singapore Airlines", "Star Alliance", ("ASIA", "EU", "NA", "OC"), ("SIN",), False, 1.07, 35.0
    ),
    CarrierProfile("BR", "EVA Air", "Star Alliance", ("ASIA", "NA", "EU"), ("TPE",), False, 0.94, 35.0),
    CarrierProfile("TK", "Turkish Airlines", "Star Alliance", ("EU", "ME", "ASIA", "NA"), ("IST",), False, 0.91, 35.0),
    # Oneworld
    CarrierProfile("BA", "British Airways", "Oneworld", ("EU", "NA", "ASIA", "ME"), ("LHR", "LGW"), False, 1.03, 45.0),
    CarrierProfile(
        "AA",
        "American Airlines",
        "Oneworld",
        ("NA", "EU", "ASIA"),
        ("JFK", "DFW", "MIA", "LAX", "ORD"),
        False,
        1.00,
        40.0,
    ),
    CarrierProfile("JL", "Japan Airlines", "Oneworld", ("ASIA", "NA", "EU"), ("HND", "NRT", "KIX"), False, 1.04, 35.0),
    CarrierProfile("CX", "Cathay Pacific", "Oneworld", ("ASIA", "NA", "EU", "OC"), ("HKG",), False, 0.97, 35.0),
    CarrierProfile("QR", "Qatar Airways", "Oneworld", ("ME", "EU", "ASIA", "NA", "OC"), ("DOH",), False, 0.96, 35.0),
    CarrierProfile("IB", "Iberia", "Oneworld", ("EU", "NA"), ("MAD", "BCN"), False, 0.95, 40.0),
    # SkyTeam
    CarrierProfile(
        "DL", "Delta Air Lines", "SkyTeam", ("NA", "EU", "ASIA"), ("JFK", "LAX", "SEA", "BOS"), False, 1.03, 40.0
    ),
    CarrierProfile("AF", "Air France", "SkyTeam", ("EU", "NA", "ASIA", "ME"), ("CDG", "ORY"), False, 1.01, 45.0),
    CarrierProfile("KL", "KLM", "SkyTeam", ("EU", "NA", "ASIA"), ("AMS",), False, 1.00, 45.0),
    CarrierProfile("KE", "Korean Air", "SkyTeam", ("ASIA", "NA", "EU"), ("ICN",), False, 0.98, 35.0),
    CarrierProfile("CI", "China Airlines", "SkyTeam", ("ASIA", "NA", "EU"), ("TPE",), False, 0.92, 35.0),
    # Low-Cost & Point-to-Point Carriers
    CarrierProfile(
        "U2",
        "easyJet",
        "LCC",
        ("EU",),
        ("LGW", "LTN", "CDG", "ORY", "MXP", "AMS", "BER", "BCN", "FCO"),
        True,
        0.58,
        55.0,
    ),
    CarrierProfile(
        "FR",
        "Ryanair",
        "LCC",
        ("EU",),
        ("STN", "DUB", "BGY", "CIA", "BER", "MAD", "BCN", "LIS", "VIE", "BUD"),
        True,
        0.52,
        60.0,
    ),
    CarrierProfile("WN", "Southwest", "LCC", ("NA",), ("OAK", "SJC", "BUR", "MDW", "BWI", "FLL"), True, 0.72, 0.0),
    CarrierProfile("B6", "JetBlue", "LCC", ("NA", "EU"), ("JFK", "BOS", "FLL", "LHR", "CDG", "AMS"), True, 0.78, 45.0),
    CarrierProfile(
        "ZG",
        "ZIPAIR Tokyo",
        "LCC",
        ("ASIA", "NA"),
        ("NRT", "SFO", "LAX", "SJC", "ICN", "BKK", "SIN", "MNL"),
        True,
        0.64,
        65.0,
    ),
    CarrierProfile(
        "AK", "AirAsia", "LCC", ("ASIA",), ("KUL", "BKK", "DMK", "SIN", "TPE", "HKG", "MNL"), True, 0.55, 50.0
    ),
    CarrierProfile(
        "TR", "Scoot", "LCC", ("ASIA", "OC"), ("SIN", "TPE", "BKK", "ICN", "NRT", "KIX", "SYD", "MEL"), True, 0.59, 55.0
    ),
)

CABIN_MULTIPLIERS: dict[ConcreteCabinClass, tuple[float, float]] = {
    # (one_way_multiplier, round_trip_half_multiplier)
    # Note how Legacy Long-Haul One-Way Business/Economy is disproportionately expensive
    # compared to half of a Round-Trip / Open-Jaw fare!
    ConcreteCabinClass.ECONOMY: (1.0, 1.0),
    ConcreteCabinClass.PREMIUM_ECONOMY: (1.68, 1.55),
    ConcreteCabinClass.BUSINESS: (3.45, 2.55),
    ConcreteCabinClass.FIRST: (5.60, 4.20),
}


def _deterministic_noise(seed_str: str) -> float:
    """Return a deterministic value in [0.0, 1.0) from a string key."""
    digest = hashlib.sha256(seed_str.encode("utf-8")).digest()
    val = int.from_bytes(digest[:4], "big")
    return (val % 10000) / 10000.0


class RealisticPricingProvider(FlightSearchProvider):
    """Generates realistic, deterministic flight options modeling GDS + LCC market dynamics."""

    def search_leg(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        orig = origin.upper()
        dest = destination.upper()
        if orig == dest:
            return []

        orig_info = get_airport(orig)
        dest_info = get_airport(dest)
        dist_km = haversine_km(orig, dest)
        nonstop_hours = estimate_nonstop_hours(orig, dest)
        is_intercontinental = orig_info.region != dest_info.region and dist_km > 3200
        is_short_haul = dist_km < 2600

        # Day-of-week & seasonal demand factor
        weekday = departure_date.weekday()  # 0=Mon .. 6=Sun
        dow_factor = {0: 1.02, 1: 0.90, 2: 0.91, 3: 0.98, 4: 1.14, 5: 1.08, 6: 1.11}[weekday]

        # Select candidate full-service carriers across the 3 alliances + relevant LCCs
        candidates: list[tuple[CarrierProfile, int, str | None]] = []

        for carrier in CARRIERS:
            if carrier.is_lcc:
                # LCCs operate either short-haul within region or specific long-haul hub pairs
                if is_short_haul and orig_info.region in carrier.regions and dest_info.region in carrier.regions:
                    if orig in carrier.hubs or dest in carrier.hubs:
                        # Most LCCs don't have First class; ZIPAIR/JetBlue have Business/Mint
                        if cabin in (ConcreteCabinClass.FIRST,) or (
                            cabin == ConcreteCabinClass.BUSINESS and carrier.code not in ("B6", "ZG", "TR")
                        ):
                            continue
                        candidates.append((carrier, 0, None))
                elif not is_short_haul and orig in carrier.hubs and dest in carrier.hubs:
                    if cabin != ConcreteCabinClass.FIRST:
                        candidates.append((carrier, 0, None))
                continue

            # Full-service carrier matching
            serves_orig_region = orig_info.region in carrier.regions
            serves_dest_region = dest_info.region in carrier.regions
            if not (serves_orig_region and serves_dest_region):
                continue

            if orig in carrier.hubs or dest in carrier.hubs:
                # Direct flight on hub carrier
                candidates.append((carrier, 0, None))
            else:
                # 1-stop via the carrier's primary hub if geographically reasonable
                via_hub = carrier.hubs[0]
                if via_hub not in (orig, dest):
                    d_via = haversine_km(orig, via_hub) + haversine_km(via_hub, dest)
                    if d_via <= dist_km * 1.48:
                        candidates.append((carrier, 1, via_hub))

        # Guarantee at least one carrier from each major alliance so multi-ticket vs single-ticket can be compared
        alliances_present = {c.alliance for c, _, _ in candidates if not c.is_lcc}
        fallback_by_alliance = {
            alliance_name: next(c for c in CARRIERS if c.alliance == alliance_name)
            for alliance_name in ("Star Alliance", "Oneworld", "SkyTeam")
        }
        for alliance_name, fb_carrier in fallback_by_alliance.items():
            if alliance_name not in alliances_present:
                via = fb_carrier.hubs[0] if fb_carrier.hubs[0] not in (orig, dest) else None
                stops = 0 if via is None else 1
                candidates.append((fb_carrier, stops, via))

        options: list[FlightLegOption] = []
        for idx, (carrier, stops_count, via_hub) in enumerate(candidates[:7]):
            seed_key = f"{orig}-{dest}-{departure_date.isoformat()}-{carrier.code}-{cabin.value}"
            noise = 0.88 + 0.26 * _deterministic_noise(seed_key)

            # Base distance curve in Economy
            base_econ = 52.0 + (dist_km * 0.072)
            if is_intercontinental:
                base_econ += 95.0

            ow_cabin_mult, rt_cabin_mult = CABIN_MULTIPLIERS[cabin]

            # Calculate half-round-trip baseline vs one-way fare
            # Full-service carriers charge a steep one-way markup on intercontinental routes
            # whereas Round-Trip / Open-Jaw tickets get the discounted RT half-fare!
            rt_half_fare = (
                base_econ
                * carrier.price_factor
                * dow_factor
                * noise
                * rt_cabin_mult
                * (0.91 if stops_count > 0 else 1.05)
            )

            if carrier.is_lcc:
                # Point-to-point pricing: One-Way is the same as half of a Round-Trip
                ow_fare = rt_half_fare
            elif is_intercontinental:
                # Legacy carrier intercontinental one-way surcharge (typically 1.38x - 1.62x of RT half-fare)
                ow_surcharge = 1.42 if cabin == ConcreteCabinClass.ECONOMY else 1.56
                ow_fare = (
                    base_econ
                    * carrier.price_factor
                    * dow_factor
                    * noise
                    * ow_cabin_mult
                    * ow_surcharge
                    * (0.92 if stops_count > 0 else 1.06)
                )
            else:
                # Regional / domestic legacy carrier one-way has a mild surcharge (1.12x)
                ow_fare = rt_half_fare * 1.12

            # Compute flight & layover durations
            if stops_count == 0 or via_hub is None:
                layover_hours = 0.0
                total_duration = round(nonstop_hours * (0.97 + 0.06 * _deterministic_noise(seed_key + "-dur")), 2)
                fn_num = 100 + int(_deterministic_noise(seed_key + "-fn") * 850)
                dep_hour = 7 + (idx * 3) % 14
                arr_hour = int((dep_hour + total_duration) % 24)
                segments = [
                    FlightSegment(
                        origin=orig,
                        destination=dest,
                        departure_date=departure_date,
                        departure_time=f"{dep_hour:02d}:15",
                        arrival_time=f"{arr_hour:02d}:40",
                        airline=carrier.code,
                        airline_name=carrier.name,
                        alliance=carrier.alliance,
                        flight_number=f"{carrier.code}{fn_num}",
                        duration_hours=total_duration,
                        cabin=cabin,
                    )
                ]
                flight_numbers = [f"{carrier.code}{fn_num}"]
                layover_airports: list[str] = []
            else:
                d1_hrs = estimate_nonstop_hours(orig, via_hub)
                d2_hrs = estimate_nonstop_hours(via_hub, dest)
                layover_hours = round(1.6 + 1.8 * _deterministic_noise(seed_key + "-lay"), 2)
                total_duration = round(d1_hrs + d2_hrs + layover_hours, 2)
                fn1 = 200 + int(_deterministic_noise(seed_key + "-fn1") * 700)
                fn2 = 200 + int(_deterministic_noise(seed_key + "-fn2") * 700)
                dep_hour = 6 + (idx * 3) % 15
                mid_hour = int((dep_hour + d1_hrs) % 24)
                arr_hour = int((dep_hour + total_duration) % 24)
                segments = [
                    FlightSegment(
                        origin=orig,
                        destination=via_hub,
                        departure_date=departure_date,
                        departure_time=f"{dep_hour:02d}:20",
                        arrival_time=f"{mid_hour:02d}:10",
                        airline=carrier.code,
                        airline_name=carrier.name,
                        alliance=carrier.alliance,
                        flight_number=f"{carrier.code}{fn1}",
                        duration_hours=d1_hrs,
                        cabin=cabin,
                    ),
                    FlightSegment(
                        origin=via_hub,
                        destination=dest,
                        departure_date=departure_date,
                        departure_time=f"{int((mid_hour + layover_hours) % 24):02d}:30",
                        arrival_time=f"{arr_hour:02d}:50",
                        airline=carrier.code,
                        airline_name=carrier.name,
                        alliance=carrier.alliance,
                        flight_number=f"{carrier.code}{fn2}",
                        duration_hours=d2_hrs,
                        cabin=cabin,
                    ),
                ]
                flight_numbers = [f"{carrier.code}{fn1}", f"{carrier.code}{fn2}"]
                layover_airports = [via_hub]

            # Business & First include checked bags by default on non-LCCs
            bag_fee = carrier.bag_fee_usd
            if not carrier.is_lcc and cabin in (ConcreteCabinClass.BUSINESS, ConcreteCabinClass.FIRST):
                bag_fee = 0.0

            leg_id = f"{orig}-{dest}-{departure_date.isoformat()}-{carrier.code}-{cabin.value}-{stops_count}"
            options.append(
                FlightLegOption(
                    leg_id=leg_id,
                    origin=orig,
                    destination=dest,
                    departure_date=departure_date,
                    cabin=cabin,
                    airline=carrier.code,
                    airline_name=carrier.name,
                    alliance=carrier.alliance,
                    flight_numbers=flight_numbers,
                    segments=segments,
                    duration_hours=total_duration,
                    stops_count=stops_count,
                    layover_airports=layover_airports,
                    layover_hours=layover_hours,
                    one_way_base_fare_usd=round(ow_fare, 2),
                    round_trip_half_fare_usd=round(rt_half_fare, 2),
                    bag_fee_per_checked_bag_usd=bag_fee,
                    includes_carry_on=carrier.code not in ("FR", "U2"),
                    is_lcc=carrier.is_lcc,
                    provider="pricing_engine",
                    from_cache=False,
                )
            )

        options.sort(key=lambda o: (o.one_way_base_fare_usd, o.duration_hours))
        return options
