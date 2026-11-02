"""Pluggable provider adapter supporting fast-flights (free scraper), SerpApi (batched), and offline simulation."""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

import httpx
from dotenv import load_dotenv

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.schemas import (
    ConcreteCabinClass,
    FlightLegOption,
    FlightSegment,
    ProviderMode,
)
from backend.app.providers.base import FlightSearchProvider
from backend.app.providers.pricing_engine import CARRIERS, RealisticPricingProvider

load_dotenv()

# Lookup table mapping 2-letter IATA airline code or airline name to (alliance, is_lcc, bag_fee_usd).
# Used ONLY to enrich live Google Flights responses when alliance metadata isn't in the payload.
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

    fallback_code = code if len(code) == 2 else (airline_name[:2].upper() if airline_name else "FL")
    return fallback_code, "Non-Aligned", False, 45.0


class CompositeFlightProvider(FlightSearchProvider):
    """Multi-mode flight provider supporting:
    - `fast_flights`: Free live Google Flights protobuf scraping with proactive rate-limiting.
    - `serpapi`: Official SerpApi Google Flights JSON API with multi-airport comma batching & quota cap.
    - `auto`: Uses `fast_flights` first (0 SerpApi quota), falling back to `serpapi` if needed.
    - `offline`: Deterministic local simulation (`RealisticPricingProvider`).
    """

    def __init__(
        self,
        cache: FlightCache | None = None,
        mode: ProviderMode = ProviderMode.AUTO,
        max_api_calls: int = 25,
        rate_limit_seconds: float | None = None,
    ) -> None:
        load_dotenv()
        self.serpapi_key = os.environ.get("SERPAPI_KEY", "").strip()
        self.cache = cache
        self.mode = mode
        self.max_api_calls = max_api_calls
        env_delay = os.environ.get("FLIGHT_SEARCH_DELAY_SECONDS", "").strip()
        self.rate_limit_seconds = (
            rate_limit_seconds if rate_limit_seconds is not None else (float(env_delay) if env_delay else None)
        )
        self.fallback = RealisticPricingProvider()
        self.api_calls_this_run = 0
        self.cap_reached_warned = False
        self.warnings: list[str] = []
        self._last_request_ts = 0.0

    def configure_for_run(
        self,
        cache: FlightCache,
        mode: ProviderMode,
        max_api_calls: int,
    ) -> None:
        load_dotenv()
        self.serpapi_key = os.environ.get("SERPAPI_KEY", "").strip()
        self.cache = cache
        self.mode = mode
        self.max_api_calls = max_api_calls
        self.api_calls_this_run = 0
        self.cap_reached_warned = False
        self.warnings = []
        cache.active_provider = mode.value

    def _throttle(self, default_delay: float) -> None:
        delay = self.rate_limit_seconds if self.rate_limit_seconds is not None else default_delay
        if delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        if self._last_request_ts > 0 and elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_ts = time.monotonic()

    def _can_make_live_call(self) -> bool:
        if self.api_calls_this_run >= self.max_api_calls:
            if not self.cap_reached_warned:
                self.cap_reached_warned = True
                self.warnings.append(
                    f"Reached per-run live API limit ({self.max_api_calls} queries). "
                    "Remaining uncached legs used local estimates; run Optimize again to fetch more live legs."
                )
            return False
        return True

    def search_leg_batch(
        self,
        origins: tuple[str, ...],
        destinations: tuple[str, ...],
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Batch multiple origins and destinations into a single query when using SerpApi,
        or query primary airport pairs when using fast-flights to conserve requests.
        """
        if self.mode == ProviderMode.OFFLINE:
            return super().search_leg_batch(origins, destinations, departure_date, cabin)

        # In SERPAPI mode, SerpApi supports comma-separated IATA codes in a single request!
        if self.mode == ProviderMode.SERPAPI:
            if not self.serpapi_key:
                self.warnings.append("SERPAPI mode selected, but SERPAPI_KEY is not set in .env or environment.")
                return super().search_leg_batch(origins, destinations, departure_date, cabin)
            if not self._can_make_live_call():
                return super().search_leg_batch(origins, destinations, departure_date, cabin)
            try:
                orig_csv = ",".join(origins)
                dest_csv = ",".join(destinations)
                if orig_csv == dest_csv and len(origins) == 1:
                    return []
                live = self._search_serpapi_google_flights(orig_csv, dest_csv, departure_date, cabin)
                if live:
                    return live
            except Exception as exc:
                self.warnings.append(f"SerpApi query ({origins[0]}→{destinations[0]}) failed: {exc}")

        # In FAST_FLIGHTS or AUTO mode, query the primary airport pair first (to avoid N*M explosion),
        # plus secondary pairs only if budget remains.
        if self.mode in (ProviderMode.FAST_FLIGHTS, ProviderMode.AUTO):
            results: list[FlightLegOption] = []
            # Prioritize primary origin -> primary destination first
            pairs = [(o, d) for o in origins[:2] for d in destinations[:2] if o.upper() != d.upper()]
            for orig, dest in pairs:
                results.extend(self.search_leg(orig, dest, departure_date, cabin))
                # If primary pair already returned plenty of options in live mode, avoid burning extra calls
                if len(results) >= 4:
                    break
            if results:
                return results

        return super().search_leg_batch(origins, destinations, departure_date, cabin)

    def search_leg(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        if origin.upper() == destination.upper():
            return []

        if self.mode == ProviderMode.OFFLINE:
            return self.fallback.search_leg(origin, destination, departure_date, cabin)

        if self.mode in (ProviderMode.FAST_FLIGHTS, ProviderMode.AUTO):
            if self._can_make_live_call():
                try:
                    ff_results = self._search_fast_flights(origin, destination, departure_date, cabin)
                    if ff_results:
                        return ff_results
                except Exception as exc:
                    if self.mode == ProviderMode.FAST_FLIGHTS:
                        self.warnings.append(
                            f"fast-flights query ({origin}→{destination} on {departure_date}) failed: {exc}"
                        )

        if self.mode in (ProviderMode.SERPAPI, ProviderMode.AUTO) and self.serpapi_key:
            if self._can_make_live_call():
                try:
                    serp_results = self._search_serpapi_google_flights(origin, destination, departure_date, cabin)
                    if serp_results:
                        return serp_results
                except Exception as exc:
                    self.warnings.append(f"SerpApi query ({origin}→{destination} on {departure_date}) failed: {exc}")

        return self.fallback.search_leg(origin, destination, departure_date, cabin)

    def _search_fast_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        from fast_flights import FlightQuery, Passengers, create_query, get_flights

        seat_map: dict[ConcreteCabinClass, Any] = {
            ConcreteCabinClass.ECONOMY: "economy",
            ConcreteCabinClass.PREMIUM_ECONOMY: "premium-economy",
            ConcreteCabinClass.BUSINESS: "business",
            ConcreteCabinClass.FIRST: "first",
        }
        self._throttle(default_delay=1.0)
        self.api_calls_this_run += 1
        if self.cache is not None:
            self.cache.record_provider_call("fast_flights")
            self.cache.active_provider = "fast_flights"

        query = create_query(
            flights=[
                FlightQuery(
                    date=departure_date.isoformat(),
                    from_airport=origin.upper(),
                    to_airport=destination.upper(),
                )
            ],
            seat=seat_map[cabin],
            trip="one-way",
            passengers=Passengers(adults=1),
            currency="USD",
            language="en",
        )
        result_list = get_flights(query)
        return self.parse_fast_flights_results(
            results=result_list,
            origin=origin.upper(),
            destination=destination.upper(),
            departure_date=departure_date,
            cabin=cabin,
        )

    @staticmethod
    def parse_fast_flights_results(
        results: list[Any],
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption]:
        """Convert fast_flights `Flights` objects into normalized `FlightLegOption` instances."""
        if not results:
            return []

        options: list[FlightLegOption] = []
        for idx, item in enumerate(results[:10]):
            price_val = getattr(item, "price", None)
            raw_flights = getattr(item, "flights", None) or []
            airlines_list = getattr(item, "airlines", None) or []
            if not price_val or not raw_flights:
                continue

            ow_price = float(price_val)
            primary_airline_name = str(airlines_list[0]) if airlines_list else "Airline"
            carrier_code, alliance, is_lcc, bag_fee = resolve_airline_metadata("", primary_airline_name)
            if not is_lcc and cabin in (ConcreteCabinClass.BUSINESS, ConcreteCabinClass.FIRST):
                bag_fee = 0.0

            segments: list[FlightSegment] = []
            flight_numbers: list[str] = []
            for seg_idx, sf in enumerate(raw_flights):
                dep_code = str(getattr(getattr(sf, "from_airport", None), "code", "") or origin)
                arr_code = str(getattr(getattr(sf, "to_airport", None), "code", "") or destination)
                dep_time_tuple = getattr(getattr(sf, "departure", None), "time", (9, 0))
                arr_time_tuple = getattr(getattr(sf, "arrival", None), "time", (17, 0))
                dep_hm = f"{int(dep_time_tuple[0]):02d}:{int(dep_time_tuple[1]):02d}"
                arr_hm = f"{int(arr_time_tuple[0]):02d}:{int(arr_time_tuple[1]):02d}"
                dur_min = float(getattr(sf, "duration", 60) or 60)
                seg_dur_hrs = round(dur_min / 60.0, 2)
                fn_code = f"{carrier_code}{100 + idx * 10 + seg_idx}"
                flight_numbers.append(fn_code)

                segments.append(
                    FlightSegment(
                        origin=dep_code,
                        destination=arr_code,
                        departure_date=departure_date,
                        departure_time=dep_hm,
                        arrival_time=arr_hm,
                        airline=carrier_code,
                        airline_name=primary_airline_name,
                        alliance=alliance,
                        flight_number=fn_code,
                        duration_hours=seg_dur_hrs,
                        cabin=cabin,
                        aircraft=str(getattr(sf, "plane_type", "Jet") or "Jet"),
                    )
                )

            actual_orig = segments[0].origin
            actual_dest = segments[-1].destination
            stops_count = max(0, len(segments) - 1)
            layover_airports = [s.destination for s in segments[:-1]]
            flight_hrs = sum(s.duration_hours for s in segments)
            layover_hours = round(stops_count * 1.75, 2)
            total_hours = round(flight_hrs + layover_hours, 2)
            rt_half = ow_price if is_lcc else round(ow_price * 0.76, 2)

            leg_id = f"{actual_orig}-{actual_dest}-{departure_date.isoformat()}-{carrier_code}-ff{idx}-{cabin.value}"
            options.append(
                FlightLegOption(
                    leg_id=leg_id,
                    origin=actual_orig,
                    destination=actual_dest,
                    departure_date=departure_date,
                    cabin=cabin,
                    airline=carrier_code,
                    airline_name=primary_airline_name,
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
                    provider="fast_flights",
                    from_cache=False,
                )
            )

        options.sort(key=lambda o: (o.one_way_base_fare_usd, o.duration_hours))
        return options

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
        self._throttle(default_delay=0.4)
        self.api_calls_this_run += 1
        if self.cache is not None:
            self.cache.record_provider_call("serpapi")
            self.cache.active_provider = "serpapi"

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
        with httpx.Client(timeout=15.0) as client:
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

        fallback_orig = origin.split(",")[0].strip().upper()
        fallback_dest = destination.split(",")[0].strip().upper()

        parsed_options: list[FlightLegOption] = []
        for idx, item in enumerate(flights_raw[:12]):
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
                dep_airport = str((seg.get("departure_airport") or {}).get("id") or fallback_orig)
                arr_airport = str(
                    (seg.get("destination_airport") or seg.get("arrival_airport") or {}).get("id") or fallback_dest
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

            actual_orig = segments[0].origin
            actual_dest = segments[-1].destination
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

            rt_half = ow_price if is_lcc else round(ow_price * 0.76, 2)
            leg_id = (
                f"{actual_orig}-{actual_dest}-{departure_date.isoformat()}-"
                f"{carrier_code}-{'_'.join(flight_numbers)}-{cabin.value}"
            )

            parsed_options.append(
                FlightLegOption(
                    leg_id=leg_id,
                    origin=actual_orig,
                    destination=actual_dest,
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
                    provider="serpapi",
                    from_cache=False,
                )
            )

        parsed_options.sort(key=lambda o: (o.one_way_base_fare_usd, o.duration_hours))
        return parsed_options
