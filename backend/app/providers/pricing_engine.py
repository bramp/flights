"""Generate synthetic flight options and estimate ticket fares.

The flight provider produces test data, not bookable flights or a fallback
for failed live searches. Fare estimates use the supplied candidate legs and
do not request or verify a ticket price.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta

from backend.app.data.airports import (
    estimate_nonstop_hours,
    get_airport,
    haversine_km,
)
from backend.app.models.queries import LegSearch, SearchResult
from backend.app.models.schemas import (
    ConcreteCabinClass,
    FareEstimate,
    FlightLegOption,
    FlightSegment,
    TicketType,
)
from backend.app.providers.base import FlightSearchProvider


@dataclass(frozen=True)
class CarrierProfile:
    """Describe reference carrier metadata and synthetic pricing parameters.

    The live adapters use the static carrier code, name, alliance, low-cost
    flag, and estimated bag fee to enrich responses. Regions, hubs, and price
    factors are approximations used only to generate simulated options.
    Carrier metadata and fees may not reflect current airline policies.

    Attributes:
        code: Airline code used in generated options.
        name: Display name of the airline.
        alliance: Alliance or low-cost carrier classification.
        regions: Approximate regions served by the simulated carrier.
        hubs: Airport codes used to generate simulated routes.
        is_lcc: Whether to apply low-cost carrier assumptions.
        price_factor: Dimensionless multiplier for simulated fares.
        bag_fee_usd: Estimated fee per checked bag in US dollars.

    Examples:
        >>> from backend.app.providers.pricing_engine import CarrierProfile
        >>> carrier = CarrierProfile(
        ...     code="XX", name="Example Air", alliance="Non-Aligned",
        ...     regions=("NA",), hubs=("SFO",), is_lcc=False,
        ...     price_factor=1.0, bag_fee_usd=40.0,
        ... )
        >>> carrier.hubs
        ('SFO',)
    """

    code: str
    name: str
    alliance: str  # "Star Alliance", "Oneworld", "SkyTeam", "LCC"
    regions: tuple[str, ...]
    hubs: tuple[str, ...]
    is_lcc: bool
    price_factor: float
    bag_fee_usd: float


# Carrier names, codes, and classifications are manually maintained and can
# become outdated. Bag fees are estimates in USD. Regions, hubs, and price
# factors are synthetic parameters used only to generate test flights.
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
    # Format: one_way_multiplier and round_trip_half_multiplier.
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


def estimate_ticket_fare(legs: list[FlightLegOption], ticket_type: TicketType) -> FareEstimate:
    """Estimate a ticket's base fare from candidate-leg fares.

    A one-way ticket or a single leg uses the sum of one-way fares. For
    multiple legs, the estimate uses round-trip half-fares only when no leg
    is low-cost and the legs share a recognized alliance or their nonblank
    carrier codes identify one carrier. Otherwise, it sums one-way fares.
    A multi-city estimate with at least three eligible legs adds 6%.

    Args:
        legs: Candidate legs covered by the proposed ticket, in travel order.
        ticket_type: Type of the proposed ticket.

    Returns:
        An estimated base fare in USD and the assumptions used. Baggage is
        excluded; ticket availability, combinability, and price are not verified.

    Raises:
        ValueError: If no legs are provided.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.queries import LegSearch
        >>> from backend.app.models.schemas import ConcreteCabinClass, TicketType
        >>> from backend.app.providers.pricing_engine import RealisticPricingProvider, estimate_ticket_fare
        >>> query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.ECONOMY)
        >>> leg = RealisticPricingProvider().search(query).options[0]
        >>> fare = estimate_ticket_fare([leg], TicketType.ONE_WAY)
        >>> fare.provenance.value, fare.amount_usd == leg.one_way_base_fare_usd
        ('estimated', True)
    """
    if not legs:
        raise ValueError("A fare estimate requires at least one flight leg.")

    one_way_total = round(sum(leg.one_way_base_fare_usd for leg in legs), 2)
    if ticket_type == TicketType.ONE_WAY or len(legs) == 1:
        return FareEstimate(
            amount_usd=one_way_total,
            assumptions=["Uses candidate-leg one-way fares; baggage and final ticket pricing are not verified."],
        )

    alliances = {leg.alliance for leg in legs}
    carriers = {leg.airline.strip().upper() for leg in legs if leg.airline.strip()}
    shared_alliance = len(alliances) == 1 and next(iter(alliances)) in ("Star Alliance", "Oneworld", "SkyTeam")
    shared_carrier = len(carriers) == 1
    if any(leg.is_lcc for leg in legs) or not (shared_alliance or shared_carrier):
        return FareEstimate(
            amount_usd=one_way_total,
            assumptions=[
                "Sums candidate-leg one-way fares because a combined fare is not available.",
                "Baggage and final ticket pricing are not verified.",
            ],
        )

    estimate = round(sum(leg.round_trip_half_fare_usd for leg in legs), 2)
    assumptions = [
        "Sums candidate-leg round-trip half-fares for the shared carrier or alliance.",
        "Baggage and final ticket pricing are not verified.",
    ]
    if ticket_type == TicketType.MULTI_CITY and len(legs) >= 3:
        estimate = round(estimate * 1.06, 2)
        assumptions.append("Applies a 6% multi-city combinability estimate.")
    return FareEstimate(amount_usd=estimate, assumptions=assumptions)


class RealisticPricingProvider(FlightSearchProvider):
    """Generate synthetic flight options for testing.

    With the same query and airport data, generated options are deterministic.
    Schedules, flight numbers, fares, and baggage details are estimates and
    are not bookable. The composite provider exposes this simulator only in
    offline mode when ``FARESPLIT_TESTING=1``.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.queries import LegSearch
        >>> from backend.app.models.schemas import ConcreteCabinClass
        >>> from backend.app.providers.pricing_engine import RealisticPricingProvider
        >>> provider = RealisticPricingProvider()
        >>> query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.ECONOMY)
        >>> result = provider.search(query)
        >>> result.status.value, result.options[0].provider
        ('complete', 'pricing_engine')
    """

    def is_simulation(self) -> bool:
        """Return true so cache wrappers do not persist simulated options."""
        return True

    def search(self, query: LegSearch) -> SearchResult:
        """Generate options for each origin and destination pair.

        Pairs with identical endpoints produce no options. Results are
        concatenated in pair order and sorted by fare and duration within
        each pair. A complete result may be empty.
        """
        results: list[FlightLegOption] = []
        for origin in query.origins:
            for destination in query.destinations:
                results.extend(self._search_pair(origin, destination, query.departure_date, query.cabin))
        return SearchResult(options=tuple(results))

    def _search_pair(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Generate up to seven synthetic options for one airport pair.

        Carrier profiles, airport metadata, estimated distances, and the
        departure date determine the candidate routes and fare assumptions.
        """
        orig = origin.upper()
        dest = destination.upper()
        if orig == dest:
            return []

        orig_info = get_airport(orig)
        dest_info = get_airport(dest)
        nonstop_hours = estimate_nonstop_hours(orig, dest)
        raw_dist_km = haversine_km(orig, dest)
        dist_km = raw_dist_km if raw_dist_km > 0 else max(400.0, (nonstop_hours - 0.65) * 830.0)
        has_both_coords = orig_info.has_coordinates and dest_info.has_coordinates
        is_intercontinental = has_both_coords and orig_info.region != dest_info.region and dist_km > 3200
        is_short_haul = dist_km < 2600
        is_same_region_short_haul = (not has_both_coords) or (orig_info.region == dest_info.region and dist_km <= 2800)

        # Day-of-week & seasonal demand factor
        weekday = departure_date.weekday()  # 0=Mon .. 6=Sun
        dow_factor = {0: 1.02, 1: 0.90, 2: 0.91, 3: 0.98, 4: 1.14, 5: 1.08, 6: 1.11}[weekday]

        # Select candidate full-service carriers across the 3 alliances + relevant LCCs
        candidates: list[tuple[CarrierProfile, int, str | None]] = []

        for carrier in CARRIERS:
            if carrier.is_lcc:
                # LCCs operate either short-haul within region or specific long-haul pairs
                if is_same_region_short_haul and orig_info.region in carrier.regions:
                    if cabin == ConcreteCabinClass.FIRST or (
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

            can_fly_direct = is_same_region_short_haul or (
                (orig in carrier.hubs or dest in carrier.hubs)
                and (
                    not is_intercontinental or (orig_info.is_major_hub and dest_info.is_major_hub and dist_km <= 10500)
                )
            )
            if can_fly_direct:
                # Direct flight on intra-regional hop or hub carrier
                candidates.append((carrier, 0, None))
            else:
                # 1-stop via the carrier's primary hub if geographically reasonable
                via_hub = next((h for h in carrier.hubs if h not in (orig, dest)), None)
                if via_hub is not None:
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
                if via is not None:
                    d_via = haversine_km(orig, via) + haversine_km(via, dest)
                    if is_same_region_short_haul or d_via > dist_km * 1.48:
                        via = None
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
                arr_date = departure_date + timedelta(days=int((dep_hour + total_duration) // 24))
                segments = [
                    FlightSegment(
                        origin=orig,
                        destination=dest,
                        departure_date=departure_date,
                        departure_time=f"{dep_hour:02d}:15",
                        arrival_date=arr_date,
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
                mid_total = dep_hour + d1_hrs
                mid_hour = int(mid_total % 24)
                mid_date = departure_date + timedelta(days=int(mid_total // 24))
                seg2_dep_total = mid_total + layover_hours
                seg2_dep_date = departure_date + timedelta(days=int(seg2_dep_total // 24))
                arr_total = dep_hour + total_duration
                arr_hour = int(arr_total % 24)
                arr_date = departure_date + timedelta(days=int(arr_total // 24))
                segments = [
                    FlightSegment(
                        origin=orig,
                        destination=via_hub,
                        departure_date=departure_date,
                        departure_time=f"{dep_hour:02d}:20",
                        arrival_date=mid_date,
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
                        departure_date=seg2_dep_date,
                        departure_time=f"{int((mid_hour + layover_hours) % 24):02d}:30",
                        arrival_date=arr_date,
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
