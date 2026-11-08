"""Tests for ticket partitioning strategies, mixed-cabin synergy, and Pareto ranking."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.queries import LegSearch, SearchIssue, SearchIssueKind, SearchResult, SearchStatus
from backend.app.models.schemas import (
    BaggageConfig,
    CabinClass,
    CabinPolicy,
    CityStopSpec,
    ConcreteCabinClass,
    FareProvenance,
    FlightLegOption,
    FlightSegment,
    StopsMode,
    StrategyKind,
    TicketType,
    TripRequest,
)
from backend.app.providers.base import FlightSearchProvider
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.providers.pricing_engine import RealisticPricingProvider, estimate_ticket_fare
from backend.app.solver.optimizer import optimize_trip


def test_optimizer_surfaces_incomplete_search_issues_for_any_provider(tmp_path: Path) -> None:
    issue = SearchIssue(SearchIssueKind.TRUNCATED, "Some airport pairs were not searched.")

    class PartialProvider(RealisticPricingProvider):
        def search(self, query: LegSearch) -> SearchResult:
            return SearchResult(options=super().search(query).options, status=SearchStatus.PARTIAL, issues=(issue,))

    request = TripRequest(
        origin_airports=["SFO"],
        destination_airports=["SFO"],
        earliest_departure=date(2026, 11, 10),
        latest_return=date(2026, 11, 15),
        stops=[CityStopSpec(id="london", label="London", airports=["LHR"], min_nights=3, max_nights=3)],
    )
    response = optimize_trip(request, PartialProvider(), FlightCache(tmp_path / "partial.db"))
    assert response.recommended.legs
    assert response.warnings.count(issue.message) == 1


def test_partitioner_mixed_cabin_open_jaw_beats_single_ticket_and_all_one_ways(
    tmp_path: Path,
) -> None:
    """When long-haul legs require Business and intra-Europe hops allow Economy,
    splitting into an Anchor Open-Jaw (Business) + Regional One-Ways (Economy)
    must be significantly cheaper than both 1 Single Multi-City Ticket (which up-fares
    all slices to Business) and All Separate One-Ways (which pay long-haul OW surcharges).
    """
    cache = FlightCache(db_path=tmp_path / "opt.db")
    provider = RealisticPricingProvider()

    req = TripRequest(
        origin_label="San Francisco",
        origin_airports=["SFO", "SJC"],
        destination_label="San Francisco",
        destination_airports=["SFO", "SJC"],
        earliest_departure=date(2026, 11, 10),
        latest_departure=date(2026, 11, 12),
        earliest_return=date(2026, 11, 22),
        latest_return=date(2026, 11, 25),
        return_leg_cabin=CabinClass.AUTO,
        ordering_mode="flexible",
        baggage=BaggageConfig(include_carry_on=True, checked_bags=1),
        cabin_policy=CabinPolicy(
            default_cabin=ConcreteCabinClass.ECONOMY,
            long_haul_cabin=ConcreteCabinClass.BUSINESS,
            long_haul_threshold_hours=6.5,
        ),
        stops=[
            CityStopSpec(
                id="lon",
                label="London",
                airports=["LHR", "LGW"],
                earliest_arrival=date(2026, 11, 10),
                latest_departure=date(2026, 11, 17),
                min_nights=4,
                max_nights=5,
                fixed_order=True,
                outbound_cabin=CabinClass.AUTO,
            ),
            CityStopSpec(
                id="par",
                label="Paris",
                airports=["CDG", "ORY"],
                earliest_arrival=date(2026, 11, 14),
                latest_departure=date(2026, 11, 21),
                min_nights=3,
                max_nights=4,
                fixed_order=False,
                outbound_cabin=CabinClass.ECONOMY,
            ),
            CityStopSpec(
                id="rom",
                label="Rome",
                airports=["FCO", "CIA"],
                earliest_arrival=date(2026, 11, 17),
                latest_departure=date(2026, 11, 25),
                min_nights=4,
                max_nights=5,
                fixed_order=False,
                outbound_cabin=CabinClass.ECONOMY,
            ),
        ],
    )

    resp = optimize_trip(req, raw_provider=provider, cache=cache)
    by_strategy = {it.strategy: it for it in resp.strategy_comparison}

    assert StrategyKind.SINGLE_TICKET in by_strategy
    assert StrategyKind.ALL_ONE_WAYS in by_strategy
    assert StrategyKind.OPEN_JAW_PLUS_REGIONAL in by_strategy
    assert StrategyKind.NESTED_ROUND_TRIPS in by_strategy
    assert StrategyKind.HUB_SPLIT in by_strategy

    oj_itin = by_strategy[StrategyKind.OPEN_JAW_PLUS_REGIONAL]
    single_itin = by_strategy[StrategyKind.SINGLE_TICKET]
    ow_itin = by_strategy[StrategyKind.ALL_ONE_WAYS]

    assert oj_itin.total_price_usd < single_itin.total_price_usd
    assert oj_itin.total_price_usd < ow_itin.total_price_usd
    assert oj_itin.savings_vs_single_ticket_usd > 0
    assert oj_itin.savings_vs_all_one_ways_usd > 0

    # Verify hub split enforces 5.5h buffer when checked_bags=1 and aligns stop_visits airports
    hub_itin = by_strategy[StrategyKind.HUB_SPLIT]
    assert hub_itin.self_transfers == 1
    assert hub_itin.min_self_transfer_buffer_hours == 5.5
    assert hub_itin.stop_visits[0].arrival_airport in ("LHR", "LGW")
    assert hub_itin.stop_visits[0].arrival_airport not in hub_itin.self_transfer_hubs

    # Every booked ticket across all strategies must have a pre-populated Google Flights URL
    for itin in resp.strategy_comparison:
        for ticket in itin.tickets:
            assert ticket.google_flights_url.startswith("https://www.google.com/travel/flights/search?tfs=")


def test_google_flights_payload_parser() -> None:
    sample_payload = {
        "best_flights": [
            {
                "price": 740,
                "total_duration": 645,
                "flights": [
                    {
                        "departure_airport": {"id": "SFO", "time": "2026-11-10 19:25"},
                        "arrival_airport": {"id": "LHR", "time": "2026-11-11 13:50"},
                        "duration": 645,
                        "airline": "British Airways",
                        "flight_number": "BA 286",
                        "airplane": "Airbus A380",
                    }
                ],
                "layovers": [],
            }
        ]
    }
    parsed = CompositeFlightProvider.parse_google_flights_payload(
        data=sample_payload,
        origin="SFO,OAK",
        destination="LHR,LGW",
        departure_date=date(2026, 11, 10),
        cabin=ConcreteCabinClass.ECONOMY,
    )
    assert len(parsed) == 1
    opt = parsed[0]
    assert opt.origin == "SFO"
    assert opt.destination == "LHR"
    assert opt.airline == "BA"
    assert opt.alliance == "Oneworld"
    assert opt.one_way_base_fare_usd == 740.0
    assert opt.stops_count == 0
    assert opt.segments[0].flight_number == "BA286"
    assert opt.provider == "serpapi"


def test_greece_london_auto_stops_keeps_ath_jtr_direct_and_warns_when_relaxed(
    tmp_path: Path,
) -> None:
    cache = FlightCache(db_path=tmp_path / "greece.db")
    provider = RealisticPricingProvider()

    req = TripRequest(
        origin_label="San Francisco",
        origin_airports=["SFO"],
        destination_label="San Francisco",
        destination_airports=["SFO"],
        earliest_departure=date(2026, 12, 11),
        latest_departure=date(2026, 12, 12),
        earliest_return=date(2026, 12, 24),
        latest_return=date(2026, 12, 26),
        return_leg_cabin=CabinClass.AUTO,
        return_leg_stops=StopsMode.AUTO,
        ordering_mode="fixed",
        stops=[
            CityStopSpec(
                id="stop-ath",
                label="Athens",
                airports=["ATH"],
                earliest_arrival=date(2026, 12, 11),
                latest_departure=date(2026, 12, 19),
                min_nights=3,
                max_nights=4,
                fixed_order=True,
                outbound_cabin=CabinClass.AUTO,
                outbound_stops=StopsMode.AUTO,
            ),
            CityStopSpec(
                id="stop-jtr",
                label="Santorini",
                airports=["JTR"],
                earliest_arrival=date(2026, 12, 11),
                latest_departure=date(2026, 12, 19),
                min_nights=3,
                max_nights=4,
                fixed_order=True,
                outbound_cabin=CabinClass.AUTO,
                outbound_stops=StopsMode.AUTO,
            ),
            CityStopSpec(
                id="stop-lon-dec",
                label="London",
                airports=["LHR", "LGW"],
                earliest_arrival=date(2026, 12, 17),
                latest_departure=date(2026, 12, 26),
                min_nights=6,
                max_nights=7,
                fixed_order=True,
                outbound_cabin=CabinClass.ECONOMY,
                outbound_stops=StopsMode.AUTO,
            ),
        ],
    )

    resp = optimize_trip(req, raw_provider=provider, cache=cache)
    rec = resp.recommended
    ath_jtr_leg = next(leg for leg in rec.legs if leg.origin == "ATH" and leg.destination == "JTR")
    assert ath_jtr_leg.stops_count == 0
    assert all(leg.stops_count <= 1 for leg in rec.legs)

    # Requesting strict Nonstop on SFO -> ATH (where only 1-stop exists) gracefully relaxes and warns
    req.stops[0].outbound_stops = StopsMode.NONSTOP
    resp_relaxed = optimize_trip(req, raw_provider=provider, cache=cache)
    assert any("relaxed to 1 stop" in w for w in resp_relaxed.warnings)


def test_non_aligned_same_carrier_can_form_open_jaw_while_distinct_unaligned_do_not(
    tmp_path: Path,
) -> None:
    class UnalignedCarrierProvider(FlightSearchProvider):
        def search(self, query: LegSearch) -> SearchResult:
            origin = query.origins[0]
            destination = query.destinations[0]
            departure_date = query.departure_date
            cabin = query.cabin
            airline = "EK" if (origin == "SFO" or destination == "SFO") else "GQ"
            airline_name = "Emirates" if airline == "EK" else "SKY express"
            return SearchResult(
                options=(
                    FlightLegOption(
                        leg_id=f"{origin}-{destination}-{departure_date.isoformat()}-{airline}",
                        origin=origin,
                        destination=destination,
                        departure_date=departure_date,
                        cabin=cabin,
                        airline=airline,
                        airline_name=airline_name,
                        alliance="Non-Aligned",
                        flight_numbers=[f"{airline}101"],
                        segments=[
                            FlightSegment(
                                origin=origin,
                                destination=destination,
                                departure_date=departure_date,
                                airline=airline,
                                airline_name=airline_name,
                                alliance="Non-Aligned",
                                flight_number=f"{airline}101",
                                duration_hours=2.0,
                                cabin=cabin,
                            )
                        ],
                        duration_hours=2.0,
                        stops_count=0,
                        one_way_base_fare_usd=1000.0 if airline == "EK" else 80.0,
                        round_trip_half_fare_usd=650.0 if airline == "EK" else 80.0,
                        bag_fee_per_checked_bag_usd=0.0,
                        provider="fast_flights",
                    ),
                )
            )

    prov = UnalignedCarrierProvider()
    leg_ek_out = prov.search(LegSearch.single("SFO", "ATH", date(2026, 12, 11), ConcreteCabinClass.BUSINESS)).options[0]
    leg_ek_ret = prov.search(LegSearch.single("LHR", "SFO", date(2026, 12, 20), ConcreteCabinClass.BUSINESS)).options[0]
    leg_gq_mid = prov.search(LegSearch.single("ATH", "LHR", date(2026, 12, 15), ConcreteCabinClass.ECONOMY)).options[0]

    same_carrier = estimate_ticket_fare([leg_ek_out, leg_ek_ret], TicketType.OPEN_JAW)
    assert same_carrier.amount_usd == 1300.0
    assert same_carrier.provenance == FareProvenance.ESTIMATED
    assert "not verified" in same_carrier.assumptions[-1]

    independent_carriers = estimate_ticket_fare([leg_ek_out, leg_gq_mid], TicketType.OPEN_JAW)
    assert independent_carriers.amount_usd == 1080.0
    assert "combined fare is not available" in independent_carriers.assumptions[0]

    req = TripRequest(
        origin_label="San Francisco",
        origin_airports=["SFO"],
        destination_label="San Francisco",
        destination_airports=["SFO"],
        earliest_departure=date(2026, 12, 11),
        latest_return=date(2026, 12, 20),
        stops=[
            CityStopSpec(id="s1", label="Athens", airports=["ATH"], min_nights=4, max_nights=4),
            CityStopSpec(id="s2", label="London", airports=["LHR"], min_nights=5, max_nights=5),
        ],
    )
    resp = optimize_trip(req, raw_provider=prov, cache=FlightCache(tmp_path / "unaligned.db"))
    by_strategy = {it.strategy: it for it in resp.strategy_comparison}
    assert StrategyKind.OPEN_JAW_PLUS_REGIONAL in by_strategy
    oj = by_strategy[StrategyKind.OPEN_JAW_PLUS_REGIONAL]
    assert oj.tickets[0].airline_or_alliance == "Emirates"
    assert oj.tickets[0].fare_estimate.amount_usd == 1300.0
    assert oj.tickets[0].fare_estimate.provenance == FareProvenance.ESTIMATED
