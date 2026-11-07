"""Tests for airport registry, nearby airport suggestions, and per-leg cabin class resolution."""

from __future__ import annotations

from base64 import b64decode
from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fast_flights.pb.flights_pb2 import Info, Seat, Trip

from backend.app.data.airports import (
    AIRPORTS,
    DISCOVERED_AIRPORTS,
    OBSERVED_PAIR_HOURS,
    candidate_intermediate_hubs,
    estimate_nonstop_hours,
    get_airport,
    haversine_km,
    same_metro_area,
    suggest_airports,
)
from backend.app.models.schemas import (
    BaggageConfig,
    CabinClass,
    CabinPolicy,
    ConcreteCabinClass,
    ConcreteStopsMode,
    StopsMode,
    StopsPolicy,
    TicketType,
)
from backend.app.providers.google_flights import (
    CompositeFlightProvider,
    build_google_flights_url,
)
from backend.app.providers.pricing_engine import RealisticPricingProvider
from backend.app.solver.cabin import (
    filter_options_by_stops,
    highest_cabin,
    resolve_leg_cabin,
    resolve_leg_max_stops,
)


@pytest.mark.parametrize(
    ("code", "city", "nearby_code"),
    [("SOU", "Southampton", "BOH"), ("BOH", "Bournemouth", "SOU")],
)
def test_south_coast_airports(code: str, city: str, nearby_code: str) -> None:
    airport = get_airport(code.lower())
    assert airport.city == city
    assert airport.name == f"{city} Airport"
    assert airport.country == "GB"
    assert airport.region == "EU"
    assert airport.metro_code == code
    assert airport.is_major_hub is False
    assert 50 < airport.lat < 52
    assert -3 < airport.lon < -1
    for query in (city, code):
        suggestion = next(item for item in suggest_airports(query) if item["code"] == code)
        assert any(item["code"] == nearby_code and not item["same_metro"] for item in suggestion["nearby"])


def test_airport_registry_preserves_record_types() -> None:
    assert len(AIRPORTS) >= 100
    for code, airport in AIRPORTS.items():
        assert airport.code == code
        assert isinstance(airport.nearby_codes, tuple)
        assert -90 <= airport.lat <= 90
        assert -180 <= airport.lon <= 180


def test_paris_nearby_airports_exclude_brussels() -> None:
    suggestions = suggest_airports("Paris")
    assert suggestions
    cdg = next(item for item in suggestions if item["code"] == "CDG")
    nearby_codes = [nb["code"] for nb in cdg["nearby"]]
    assert "ORY" in nearby_codes
    assert "BVA" in nearby_codes
    assert "BRU" not in nearby_codes


def test_same_metro_area_and_distance() -> None:
    assert same_metro_area("LHR", "LGW") is True
    assert same_metro_area("HND", "NRT") is True
    assert same_metro_area("CDG", "BRU") is False
    assert haversine_km("SFO", "LHR") > 8000
    assert estimate_nonstop_hours("SFO", "LHR") > 9.0
    assert estimate_nonstop_hours("LHR", "CDG") < 2.0


def test_candidate_intermediate_hubs() -> None:
    # Long-haul SFO -> BKK should find sensible Pacific/Asian gateway hubs
    hubs = candidate_intermediate_hubs("SFO", "BKK", max_hubs=3)
    assert len(hubs) >= 1
    assert any(h in ("TPE", "HND", "NRT", "ICN", "HKG") for h in hubs)
    # Short-haul LHR -> CDG should not suggest hub splitting
    assert candidate_intermediate_hubs("LHR", "CDG") == []


def test_resolve_leg_cabin_auto_and_explicit() -> None:
    policy = CabinPolicy(
        default_cabin=ConcreteCabinClass.ECONOMY,
        long_haul_cabin=ConcreteCabinClass.BUSINESS,
        long_haul_threshold_hours=6.5,
    )
    # Long-haul leg (SFO -> LHR ~10.9h) under AUTO resolves to BUSINESS
    assert resolve_leg_cabin("SFO", "LHR", CabinClass.AUTO, policy) == ConcreteCabinClass.BUSINESS
    # Short-haul leg (LHR -> CDG ~1.1h) under AUTO resolves to ECONOMY
    assert resolve_leg_cabin("LHR", "CDG", CabinClass.AUTO, policy) == ConcreteCabinClass.ECONOMY
    # Explicit override is always respected regardless of flight length
    assert resolve_leg_cabin("SFO", "LHR", CabinClass.ECONOMY, policy) == ConcreteCabinClass.ECONOMY
    assert resolve_leg_cabin("LHR", "CDG", CabinClass.FIRST, policy) == ConcreteCabinClass.FIRST


def test_highest_cabin_ranking() -> None:
    assert highest_cabin([ConcreteCabinClass.ECONOMY, ConcreteCabinClass.BUSINESS]) == ConcreteCabinClass.BUSINESS
    assert highest_cabin([ConcreteCabinClass.PREMIUM_ECONOMY, ConcreteCabinClass.FIRST]) == ConcreteCabinClass.FIRST


def _decode_google_flights_tfs(url: str) -> Info:
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.google.com"
    assert parsed.path == "/travel/flights/search"
    qs = parse_qs(parsed.query)
    assert qs.get("hl") == ["en"]
    assert qs.get("curr") == ["USD"]
    tfs_b64 = qs["tfs"][0]
    info = Info()
    info.ParseFromString(b64decode(tfs_b64))
    return info


def test_build_google_flights_url_encodes_slices_trip_type_cabin_and_baggage() -> None:
    assert build_google_flights_url([], TicketType.ONE_WAY) == "https://www.google.com/travel/flights"

    prov = RealisticPricingProvider()
    sfo_lhr = prov.search_leg("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)[0]
    lhr_sfo = prov.search_leg("LHR", "SFO", date(2026, 11, 20), ConcreteCabinClass.BUSINESS)[0]
    cdg_sfo = prov.search_leg("CDG", "SFO", date(2026, 11, 20), ConcreteCabinClass.ECONOMY)[0]
    lhr_cdg = prov.search_leg("LHR", "CDG", date(2026, 11, 15), ConcreteCabinClass.ECONOMY)[0]

    bags = BaggageConfig(include_carry_on=True, checked_bags=2)

    # 1. Single-slice One-Way
    ow_url = build_google_flights_url([lhr_cdg], TicketType.ONE_WAY, bags)
    ow_info = _decode_google_flights_tfs(ow_url)
    assert ow_info.trip == Trip.ONE_WAY
    assert ow_info.seat == Seat.ECONOMY
    assert len(ow_info.data) == 1
    assert ow_info.data[0].from_airport.airport == "LHR"
    assert ow_info.data[0].to_airport.airport == "CDG"
    assert ow_info.data[0].date == "2026-11-15"
    assert ow_info.baggage.carry_on_bags == 1
    assert ow_info.baggage.checked_bags == 2

    # 2. Exact 2-slice symmetric Round-Trip
    rt_url = build_google_flights_url([sfo_lhr, lhr_sfo], TicketType.ROUND_TRIP, bags)
    rt_info = _decode_google_flights_tfs(rt_url)
    assert rt_info.trip == Trip.ROUND_TRIP
    assert rt_info.seat == Seat.BUSINESS
    assert [(d.from_airport.airport, d.to_airport.airport, d.date) for d in rt_info.data] == [
        ("SFO", "LHR", "2026-11-10"),
        ("LHR", "SFO", "2026-11-20"),
    ]

    # 3. 2-slice Open-Jaw (uses MULTI_CITY in Google Flights protobuf so both airport pairs are preserved)
    oj_url = build_google_flights_url([sfo_lhr, cdg_sfo], TicketType.OPEN_JAW)
    oj_info = _decode_google_flights_tfs(oj_url)
    assert oj_info.trip == Trip.MULTI_CITY
    assert oj_info.seat == Seat.BUSINESS  # highest cabin across slices
    assert [(d.from_airport.airport, d.to_airport.airport) for d in oj_info.data] == [
        ("SFO", "LHR"),
        ("CDG", "SFO"),
    ]

    # 4. 3-slice Multi-City
    mc_url = build_google_flights_url([sfo_lhr, lhr_cdg, cdg_sfo], TicketType.MULTI_CITY, bags)
    mc_info = _decode_google_flights_tfs(mc_url)
    assert mc_info.trip == Trip.MULTI_CITY
    assert len(mc_info.data) == 3


def test_resolve_leg_max_stops_and_filtering() -> None:
    policy = StopsPolicy(
        short_haul_stops=ConcreteStopsMode.NONSTOP,
        long_haul_stops=ConcreteStopsMode.ONE_STOP,
        nonstop_threshold_hours=4.5,
    )
    # ATH -> JTR (~0.9h < 4.5h) under AUTO resolves to 0 stops (Nonstop)
    assert resolve_leg_max_stops("ATH", "JTR", StopsMode.AUTO, policy) == 0
    # SFO -> ATH (~13.6h >= 4.5h) under AUTO resolves to 1 stop
    assert resolve_leg_max_stops("SFO", "ATH", StopsMode.AUTO, policy) == 1
    # Explicit overrides
    assert resolve_leg_max_stops("SFO", "ATH", StopsMode.NONSTOP, policy) == 0
    assert resolve_leg_max_stops("ATH", "JTR", StopsMode.ANY, policy) is None

    prov = RealisticPricingProvider()
    ath_jtr = prov.search_leg("ATH", "JTR", date(2026, 12, 15), ConcreteCabinClass.ECONOMY)
    assert ath_jtr
    assert all(o.stops_count == 0 for o in filter_options_by_stops(ath_jtr, 0))

    # When no nonstop exists (e.g. SFO -> ATH), filter_options_by_stops(0) falls back to 1-stop
    sfo_ath = prov.search_leg("SFO", "ATH", date(2026, 12, 11), ConcreteCabinClass.BUSINESS)
    filtered_sfo_ath = filter_options_by_stops(sfo_ath, 0)
    assert filtered_sfo_ath
    assert all(o.stops_count == 1 for o in filtered_sfo_ath)


def test_unknown_airport_never_invents_fake_coordinates_and_learns_from_search() -> None:
    DISCOVERED_AIRPORTS.pop("CHQ", None)
    OBSERVED_PAIR_HOURS.pop(("ATH", "CHQ"), None)
    OBSERVED_PAIR_HOURS.pop(("CHQ", "ATH"), None)

    unknown = get_airport("CHQ")
    assert unknown.has_coordinates is False
    # Missing airport data must not invent random ocean coordinates or upgrade to long-haul Business
    assert haversine_km("ATH", "CHQ") == 0.0
    assert candidate_intermediate_hubs("ATH", "CHQ") == []
    policy = CabinPolicy(
        default_cabin=ConcreteCabinClass.ECONOMY,
        long_haul_cabin=ConcreteCabinClass.BUSINESS,
        long_haul_threshold_hours=6.5,
    )
    assert resolve_leg_cabin("ATH", "CHQ", CabinClass.AUTO, policy) == ConcreteCabinClass.ECONOMY

    # Simulate a fast_flights ResultList with metadata.airlines and airport names/durations
    class FakeResultList(list):  # type: ignore[type-arg]
        pass

    fake_results = FakeResultList(
        [
            SimpleNamespace(
                type="multi",
                price=62,
                airlines=["Aegean"],
                flights=[
                    SimpleNamespace(
                        from_airport=SimpleNamespace(code="ATH", name="Athens International Airport"),
                        to_airport=SimpleNamespace(code="CHQ", name="Chania International Airport"),
                        departure=SimpleNamespace(date=(2026, 12, 15), time=(10, 0)),
                        arrival=SimpleNamespace(date=(2026, 12, 15), time=(10, 50)),
                        duration=50,
                        plane_type="Airbus A320",
                    )
                ],
            )
        ]
    )
    fake_results.metadata = SimpleNamespace(
        airlines=[SimpleNamespace(code="A3", name="Aegean")],
        alliances=[],
    )

    parsed = CompositeFlightProvider.parse_fast_flights_results(
        fake_results,
        origin="ATH",
        destination="CHQ",
        departure_date=date(2026, 12, 15),
        cabin=ConcreteCabinClass.ECONOMY,
    )
    assert len(parsed) == 1
    assert parsed[0].airline == "A3"
    assert parsed[0].alliance == "Star Alliance"

    # Now CHQ airport name/city and exact observed flight duration are known from the search!
    learned = get_airport("CHQ")
    assert learned.name == "Chania International Airport"
    assert learned.city == "Chania"
    assert estimate_nonstop_hours("ATH", "CHQ") == 0.83

    # Multi-carrier itinerary mixing an aligned airline and an LCC is marked LCC/Non-Aligned,
    # and multi-stop total air duration is recorded for the endpoint pair (SFO -> CHQ).
    OBSERVED_PAIR_HOURS.pop(("SFO", "CHQ"), None)
    mixed_results = FakeResultList(
        [
            SimpleNamespace(
                type="multi",
                price=1100,
                airlines=["Aegean", "easyJet"],
                flights=[
                    SimpleNamespace(
                        from_airport=SimpleNamespace(code="SFO", name="San Francisco International Airport"),
                        to_airport=SimpleNamespace(code="ATH", name="Athens International Airport"),
                        departure=SimpleNamespace(date=(2026, 12, 15), time=(10, 0)),
                        arrival=SimpleNamespace(date=(2026, 12, 16), time=(6, 0)),
                        duration=720,
                        plane_type="Boeing 787",
                    ),
                    SimpleNamespace(
                        from_airport=SimpleNamespace(code="ATH", name="Athens International Airport"),
                        to_airport=SimpleNamespace(code="CHQ", name="Chania International Airport"),
                        departure=SimpleNamespace(date=(2026, 12, 16), time=(8, 0)),
                        arrival=SimpleNamespace(date=(2026, 12, 16), time=(8, 50)),
                        duration=50,
                        plane_type="Airbus A320",
                    ),
                ],
            )
        ]
    )
    mixed_results.metadata = SimpleNamespace(
        airlines=[
            SimpleNamespace(code="A3", name="Aegean"),
            SimpleNamespace(code="U2", name="easyJet"),
        ],
        alliances=[],
    )
    parsed_mixed = CompositeFlightProvider.parse_fast_flights_results(
        mixed_results,
        origin="SFO",
        destination="CHQ",
        departure_date=date(2026, 12, 15),
        cabin=ConcreteCabinClass.BUSINESS,
    )
    assert len(parsed_mixed) == 1
    assert parsed_mixed[0].is_lcc is True
    assert parsed_mixed[0].alliance == "LCC"
    assert estimate_nonstop_hours("SFO", "CHQ") == 12.83
    assert resolve_leg_cabin("SFO", "CHQ", CabinClass.AUTO, policy) == ConcreteCabinClass.BUSINESS
