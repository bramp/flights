"""Tests for ticket partitioning strategies, mixed-cabin synergy, and Pareto ranking."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.schemas import (
    BaggageConfig,
    CabinClass,
    CabinPolicy,
    CityStopSpec,
    ConcreteCabinClass,
    StrategyKind,
    TripRequest,
)
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.providers.pricing_engine import RealisticPricingProvider
from backend.app.solver.optimizer import optimize_trip


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
        origin="SFO",
        destination="LHR",
        departure_date=date(2026, 11, 10),
        cabin=ConcreteCabinClass.ECONOMY,
    )
    assert len(parsed) == 1
    opt = parsed[0]
    assert opt.airline == "BA"
    assert opt.alliance == "Oneworld"
    assert opt.one_way_base_fare_usd == 740.0
    assert opt.stops_count == 0
    assert opt.segments[0].flight_number == "BA286"
