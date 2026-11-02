"""Tests for flexible city ordering (TSPTW) and schedule DAG generation."""

from __future__ import annotations

from datetime import date

from backend.app.models.schemas import CityStopSpec, TripRequest
from backend.app.solver.route_dag import (
    generate_candidate_schedules,
    generate_city_orders,
)


def _sample_trip(ordering_mode: str = "flexible") -> TripRequest:
    return TripRequest(
        origin_label="San Francisco",
        origin_airports=["SFO"],
        destination_label="San Francisco",
        destination_airports=["SFO"],
        earliest_departure=date(2026, 11, 10),
        latest_departure=date(2026, 11, 13),
        earliest_return=date(2026, 11, 21),
        latest_return=date(2026, 11, 25),
        ordering_mode=ordering_mode,  # type: ignore[arg-type]
        stops=[
            CityStopSpec(
                id="s1",
                label="London",
                airports=["LHR"],
                earliest_arrival=date(2026, 11, 10),
                latest_departure=date(2026, 11, 17),
                min_nights=3,
                max_nights=5,
                fixed_order=True,
            ),
            CityStopSpec(
                id="s2",
                label="Rome",
                airports=["FCO"],
                earliest_arrival=date(2026, 11, 13),
                latest_departure=date(2026, 11, 25),
                min_nights=3,
                max_nights=5,
                fixed_order=False,
            ),
            CityStopSpec(
                id="s3",
                label="Paris",
                airports=["CDG"],
                earliest_arrival=date(2026, 11, 13),
                latest_departure=date(2026, 11, 25),
                min_nights=3,
                max_nights=5,
                fixed_order=False,
            ),
        ],
    )


def test_fixed_vs_flexible_city_orders() -> None:
    fixed_req = _sample_trip("fixed")
    fixed_orders = generate_city_orders(fixed_req)
    assert len(fixed_orders) == 1
    assert [s.id for s in fixed_orders[0]] == ["s1", "s2", "s3"]

    flex_req = _sample_trip("flexible")
    flex_orders = generate_city_orders(flex_req)
    assert len(flex_orders) == 2
    # Stop s1 is pinned at index 0 in all generated orders
    for order in flex_orders:
        assert order[0].id == "s1"


def test_generate_candidate_schedules_respects_windows() -> None:
    req = _sample_trip("flexible")
    schedules = generate_candidate_schedules(req, max_schedules=10)
    assert len(schedules) >= 1
    for sched in schedules:
        assert len(sched.legs) == len(req.stops) + 1
        assert sched.legs[0].departure_date >= req.earliest_departure
        assert sched.legs[-1].departure_date <= req.latest_return
