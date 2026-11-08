"""Two-tier SQLite cache for granular individual flights and multi-slice ticket quotes."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from backend.app.data.airports import record_observed_duration
from backend.app.models.queries import LegSearch, SearchResult, SearchStatus
from backend.app.models.schemas import (
    CacheStats,
    FlightLegOption,
)


class FlightCache:
    """Persistent SQLite store indexing both individual flights and slice queries."""

    def __init__(self, db_path: str | Path = "flights_cache.db", ttl_seconds: int = 86400 * 7) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = ttl_seconds
        self.session_hits = 0
        self.session_misses = 0
        self.session_serpapi_calls = 0
        self.session_fast_flights_calls = 0
        self.active_provider = "auto"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leg_search_cache (
                    cache_key TEXT PRIMARY KEY,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    departure_date TEXT NOT NULL,
                    cabin TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS granular_flights (
                    leg_id TEXT PRIMARY KEY,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    departure_date TEXT NOT NULL,
                    cabin TEXT NOT NULL,
                    airline TEXT NOT NULL,
                    alliance TEXT NOT NULL,
                    one_way_fare REAL NOT NULL,
                    rt_half_fare REAL NOT NULL,
                    duration_hours REAL NOT NULL,
                    stops_count INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_granular_lookup
                ON granular_flights (origin, destination, departure_date, cabin)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_quote_cache (
                    quote_key TEXT PRIMARY KEY,
                    ticket_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_usage (
                    provider TEXT PRIMARY KEY,
                    call_count INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                DELETE FROM leg_search_cache
                WHERE EXISTS (
                    SELECT 1 FROM json_each(leg_search_cache.payload_json)
                    WHERE COALESCE(json_extract(value, '$.provider'), 'pricing_engine') = 'pricing_engine'
                )
                """
            )
            conn.execute(
                """
                DELETE FROM granular_flights
                WHERE COALESCE(json_extract(payload_json, '$.provider'), 'pricing_engine') = 'pricing_engine'
                """
            )
            conn.execute(
                """
                DELETE FROM ticket_quote_cache
                WHERE json_type(payload_json, '$.providers') IS NULL
                    OR EXISTS (
                        SELECT 1 FROM json_each(ticket_quote_cache.payload_json, '$.providers')
                        WHERE value = 'pricing_engine'
                    )
                """
            )

    def reset_session_counters(self) -> None:
        self.session_hits = 0
        self.session_misses = 0
        self.session_serpapi_calls = 0
        self.session_fast_flights_calls = 0

    def record_provider_call(self, provider_name: str) -> None:
        """Record an external live query in both session counters and persistent SQLite usage tracking."""
        now = time.time()
        if provider_name == "serpapi":
            self.session_serpapi_calls += 1
        elif provider_name == "fast_flights":
            self.session_fast_flights_calls += 1
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_usage (provider, call_count, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    call_count = call_count + 1,
                    updated_at = excluded.updated_at
                """,
                (provider_name, now),
            )

    @staticmethod
    def make_leg_key(query: LegSearch, provider_scope: str) -> str:
        origins = ",".join(query.origins)
        destinations = ",".join(query.destinations)
        return f"search-v3:{provider_scope}:{origins}:{destinations}:{query.departure_date.isoformat()}:{query.cabin.value}"

    def get_leg_options(self, query: LegSearch, *, provider_scope: str) -> list[FlightLegOption] | None:
        key = self.make_leg_key(query, provider_scope)
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, updated_at FROM leg_search_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row and (now - float(row["updated_at"])) <= self.ttl_seconds:
                self.session_hits += 1
                raw_list = json.loads(row["payload_json"])
                options = [FlightLegOption.model_validate(item) for item in raw_list]
                for opt in options:
                    opt.from_cache = True
                    for seg in opt.segments:
                        record_observed_duration(seg.origin, seg.destination, seg.duration_hours)
                return options

        self.session_misses += 1
        return None

    def store_leg_options(self, query: LegSearch, result: SearchResult, *, provider_scope: str) -> None:
        options = result.options
        if (
            result.status != SearchStatus.COMPLETE
            or not options
            or any(o.provider == "pricing_engine" for o in options)
        ):
            return
        key = self.make_leg_key(query, provider_scope)
        now = time.time()
        serialized_list = json.dumps([opt.model_dump(mode="json") for opt in options])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO leg_search_cache
                (cache_key, origin, destination, departure_date, cabin, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    ",".join(query.origins),
                    ",".join(query.destinations),
                    query.departure_date.isoformat(),
                    query.cabin.value,
                    serialized_list,
                    now,
                ),
            )
            for opt in options:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO granular_flights
                    (leg_id, origin, destination, departure_date, cabin, airline, alliance,
                     one_way_fare, rt_half_fare, duration_hours, stops_count, payload_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        opt.leg_id,
                        opt.origin.upper(),
                        opt.destination.upper(),
                        opt.departure_date.isoformat(),
                        opt.cabin.value,
                        opt.airline,
                        opt.alliance,
                        opt.one_way_base_fare_usd,
                        opt.round_trip_half_fare_usd,
                        opt.duration_hours,
                        opt.stops_count,
                        json.dumps(opt.model_dump(mode="json")),
                        now,
                    ),
                )

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM leg_search_cache")
            conn.execute("DELETE FROM granular_flights")
            conn.execute("DELETE FROM ticket_quote_cache")
        self.reset_session_counters()

    def get_ticket_quote(self, quote_key: str) -> dict[str, object] | None:
        """Retrieve a cached multi-slice ticket quote (RT, Open-Jaw, Multi-City) by signature."""
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, updated_at FROM ticket_quote_cache WHERE quote_key = ?",
                (quote_key,),
            ).fetchone()
            if row and (now - float(row["updated_at"])) <= self.ttl_seconds:
                self.session_hits += 1
                data: dict[str, object] = json.loads(row["payload_json"])
                return data
        self.session_misses += 1
        return None

    def store_ticket_quote(
        self,
        quote_key: str,
        ticket_type: str,
        payload: dict[str, object],
    ) -> None:
        """Store a priced multi-slice ticket quote in SQLite."""
        providers = payload.get("providers")
        if not isinstance(providers, list) or not providers or "pricing_engine" in providers:
            return
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ticket_quote_cache
                (quote_key, ticket_type, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (quote_key, ticket_type, json.dumps(payload), now),
            )

    def get_stats(self) -> CacheStats:
        with self._connect() as conn:
            flights_count = conn.execute("SELECT COUNT(*) AS cnt FROM granular_flights").fetchone()["cnt"]
            leg_queries_count = conn.execute("SELECT COUNT(*) AS cnt FROM leg_search_cache").fetchone()["cnt"]
            ticket_quotes_count = conn.execute("SELECT COUNT(*) AS cnt FROM ticket_quote_cache").fetchone()["cnt"]
            serp_row = conn.execute("SELECT call_count FROM provider_usage WHERE provider = 'serpapi'").fetchone()
            total_serp = int(serp_row["call_count"]) if serp_row else 0
        return CacheStats(
            cache_hits=self.session_hits,
            cache_misses=self.session_misses,
            total_cached_flights_in_db=int(flights_count),
            total_cached_quotes_in_db=int(leg_queries_count) + int(ticket_quotes_count),
            serpapi_calls_this_run=self.session_serpapi_calls,
            fast_flights_calls_this_run=self.session_fast_flights_calls,
            total_serpapi_calls_logged=total_serp,
            active_provider=self.active_provider,
        )
