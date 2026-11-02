"""Pluggable provider adapter combining live Google Flights / SerpApi lookup with deterministic fallback."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import httpx

from backend.app.models.schemas import (
    ConcreteCabinClass,
    FlightLegOption,
    FlightSegment,
)
from backend.app.providers.base import FlightSearchProvider
from backend.app.providers.pricing_engine import CARRIERS, RealisticPricingProvider

# Lookup table mapping 2-letter IATA airline code or airline name to (alliance, is_lcc, bag_fee_usd).
# Used ONLY to enrich live Google Flights responses when alliance metadata isn't in the JSON payload.
AIRLINE_METADATA_BY_CODE: dict[str, tuple[str, bool, float]] = {
    c.code: (c.alliance, c.is_lcc, c.bag_fee_usd) for c in CARRIERS
}
AIRLINE_METADATA_BY_NAME: dict[str, tuple[str, str, bool, float]] = {
    c.name.lower(): (c.code, c.alliance, c.is_lcc, c.bag_fee_usd) for c in CARRIERS
}


def resolve_airline_metadata(airline_code: str, airline_name: str) -> tuple[str, str, bool, float]:
    """Return (code, alliance, is_lcc, default_bag_fee) from live carrier code or name."""
    code = airline_code.strip().upper()
    if code in AIRLINE_METADATA_BY_CODE:
        alliance, is_lcc, bag_fee = AIRLINE_METADATA_BY_CODE[code]
        return code, alliance, is_lcc, bag_fee

    lower_name = airline_name.strip().lower()
    for known_name, (k_code, alliance, is_lcc, bag_fee) in AIRLINE_METADATA_BY_NAME.items():
        if known_name in lower_name or lower_name in known_name:
            return (code or k_code), alliance, is_lcc, bag_fee

    fallback_code = code if len(code) == 2 else airline_name[:2].upper()
    return fallback_code, "Non-Aligned", False, 45.0


class CompositeFlightProvider(FlightSearchProvider):
    """Queries live Google Flights (via SerpApi or fast-flights when available/configured),
    falling back to RealisticPricingProvider when offline or unconfigured.
    """

    def __init__(self) -> None:
        self.serpapi_key = os.environ.get("SERPAPI_KEY", "").strip()
        self.fallback = RealisticPricingProvider()

    def search_leg(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        if self.serpapi_key:
            try:
                live_results = self._search_serpapi_google_flights(origin, destination, departure_date, cabin)
                if live_results:
                    return live_results
            except Exception:
                # Fall back cleanly if offline or rate-limited
                pass
        return self.fallback.search_leg(origin, destination, departure_date, cabin)

    def _search_serpapi_google_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        cabin_map = {
            ConcreteCabinClass.ECONOMY: "1",
            ConcreteCabinClass.PREMIUM_ECONOMY: "2",
            ConcreteCabinClass.BUSINESS: "3",
            ConcreteCabinClass.FIRST: "4",
        }
        params = {
            "engine": "google_flights",
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "outbound_date": departure_date.isoformat(),
            "type": "2",  # One-way
            "travel_class": cabin_map[cabin],
            "currency": "USD",
            "hl": "en",
            "api_key": self.serpapi_key,
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.get("https://serpapi.com/search.json", params=params)
            resp.raise_for_status()
            data = resp.json()

        return self.parse_google_flights_payload(
            data=data,
            origin=origin.upper(),
            destination=destination.upper(),
            departure_date=departure_date,
            cabin=cabin,
        )

    @staticmethod
    def parse_google_flights_payload(
        data: dict[str, Any],
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Parse actual Google Flights JSON itineraries into normalized FlightLegOption objects.
        Extracts real segments, layover hubs, durations, flight numbers, and fares directly
        from the response payload without relying on synthetic hub or region tables.
        """
        flights_raw: list[dict[str, Any]] = (data.get("best_flights") or []) + (data.get("other_flights") or [])
        if not flights_raw:
            return []

        parsed_options: list[FlightLegOption] = []
        for idx, item in enumerate(flights_raw[:10]):
            price_raw = item.get("price")
            if price_raw is None:
                continue
            ow_price = float(price_raw)
            total_duration_min = float(item.get("total_duration") or 0.0)
            raw_segments: list[dict[str, Any]] = item.get("flights") or []
            raw_layovers: list[dict[str, Any]] = item.get("layovers") or []
            if not raw_segments:
                continue

            first_seg = raw_segments[0]
            raw_fn = str(first_seg.get("flight_number") or "").replace(" ", "")
            raw_airline_name = str(first_seg.get("airline") or "Airline")
            raw_code = raw_fn[:2] if len(raw_fn) >= 2 else ""

            carrier_code, alliance, is_lcc, bag_fee = resolve_airline_metadata(raw_code, raw_airline_name)
            if not is_lcc and cabin in (ConcreteCabinClass.BUSINESS, ConcreteCabinClass.FIRST):
                bag_fee = 0.0

            segments: list[FlightSegment] = []
            flight_numbers: list[str] = []
            for seg in raw_segments:
                dep_airport = str((seg.get("departure_airport") or {}).get("id") or origin)
                arr_airport = str(
                    (seg.get("destination_airport") or seg.get("arrival_airport") or {}).get("id") or destination
                )
                dep_time_full = str((seg.get("departure_airport") or {}).get("time") or "09:00")
                arr_time_full = str((seg.get("arrival_airport") or {}).get("time") or "17:00")
                dep_hm = dep_time_full.split(" ")[-1][:5]
                arr_hm = arr_time_full.split(" ")[-1][:5]
                seg_dur_hrs = round(float(seg.get("duration") or 60.0) / 60.0, 2)
                fn_clean = str(seg.get("flight_number") or f"{carrier_code}{100 + idx}").replace(" ", "")
                flight_numbers.append(fn_clean)

                segments.append(
                    FlightSegment(
                        origin=dep_airport,
                        destination=arr_airport,
                        departure_date=departure_date,
                        departure_time=dep_hm,
                        arrival_time=arr_hm,
                        airline=carrier_code,
                        airline_name=raw_airline_name,
                        alliance=alliance,
                        flight_number=fn_clean,
                        duration_hours=seg_dur_hrs,
                        cabin=cabin,
                        aircraft=str(seg.get("airplane") or "Jet"),
                    )
                )

            layover_airports = [str(lay.get("id")) for lay in raw_layovers if lay.get("id")]
            if not layover_airports and len(segments) > 1:
                layover_airports = [s.destination for s in segments[:-1]]

            layover_hours = round(sum(float(lay.get("duration") or 0.0) for lay in raw_layovers) / 60.0, 2)
            total_hours = (
                round(total_duration_min / 60.0, 2)
                if total_duration_min > 0
                else round(sum(s.duration_hours for s in segments) + layover_hours, 2)
            )
            stops_count = max(0, len(segments) - 1)

            # Estimate round-trip half-fare when only one-way search was run
            rt_half = ow_price if is_lcc else round(ow_price * 0.76, 2)
            leg_id = (
                f"{origin}-{destination}-{departure_date.isoformat()}-"
                f"{carrier_code}-{'_'.join(flight_numbers)}-{cabin.value}"
            )

            parsed_options.append(
                FlightLegOption(
                    leg_id=leg_id,
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    cabin=cabin,
                    airline=carrier_code,
                    airline_name=raw_airline_name,
                    alliance=alliance,
                    flight_numbers=flight_numbers,
                    segments=segments,
                    duration_hours=total_hours,
                    stops_count=stops_count,
                    layover_airports=layover_airports,
                    layover_hours=layover_hours,
                    one_way_base_fare_usd=round(ow_price, 2),
                    round_trip_half_fare_usd=rt_half,
                    bag_fee_per_checked_bag_usd=bag_fee,
                    includes_carry_on=True,
                    is_lcc=is_lcc,
                    provider="google_flights",
                    from_cache=False,
                )
            )

        parsed_options.sort(key=lambda o: (o.one_way_base_fare_usd, o.duration_hours))
        return parsed_options
