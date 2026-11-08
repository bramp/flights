"""Abstract flight search provider and cache-backed provider decorator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from backend.app.cache.sqlite_cache import FlightCache
from backend.app.models.queries import LegSearch, SearchIssue, SearchResult

ProgressCallback = Callable[[dict[str, Any]], None]


class FlightSearchProvider(ABC):
    """Protocol for fetching candidate flight options."""

    def is_simulation(self) -> bool:
        return False

    def cache_scope(self) -> str:
        """Identify provider settings that affect the candidates returned by a search."""
        return f"{type(self).__module__}.{type(self).__qualname__}"

    @abstractmethod
    def search(self, query: LegSearch) -> SearchResult:
        """Return candidate flights and whether the requested search completed."""


class CachedFlightProvider(FlightSearchProvider):
    """Wrap a FlightSearchProvider with persistent SQLite search caching."""

    def __init__(
        self,
        delegate: FlightSearchProvider,
        cache: FlightCache,
        force_refresh: bool = False,
        progress_callback: ProgressCallback | None = None,
        planned_queries: set[LegSearch] | None = None,
    ) -> None:
        self.delegate = delegate
        self.cache = cache
        self.force_refresh = force_refresh
        self.progress_callback = progress_callback
        self.planned_queries: set[LegSearch] = set(planned_queries) if planned_queries else set()
        self.completed_queries: set[LegSearch] = set()
        self._run_results: dict[LegSearch, SearchResult] = {}
        self.search_issues: list[SearchIssue] = []
        self._provider_scope = delegate.cache_scope()
        self.schedule_index: int = 1
        self.schedules_total: int = 1
        self.current_schedule_route: str = ""
        self.current_strategy_label: str = ""
        self.strategies_completed: int = 0
        self.strategies_total: int = 1

    @staticmethod
    def format_query_label(query: LegSearch) -> str:
        orig_display = ", ".join(query.origins)
        dest_display = ", ".join(query.destinations)
        cabin_display = query.cabin.value.replace("_", " ").title()
        return f"{orig_display} → {dest_display} ({query.departure_date.isoformat()} · {cabin_display})"

    def compute_progress_pct(self) -> int:
        total_q = max(1, len(self.planned_queries))
        done_q = min(total_q, len(self.completed_queries))
        q_ratio = done_q / total_q
        s_ratio = self.strategies_completed / max(1, self.strategies_total)
        pct = round((q_ratio * 0.75 + s_ratio * 0.25) * 95) + 3
        return max(3, min(99, pct))

    def emit_progress(
        self,
        phase: str,
        current_query: str,
        last_query: dict[str, Any] | None = None,
        progress_pct: int | None = None,
    ) -> None:
        if self.progress_callback is None:
            return
        total_q = max(len(self.planned_queries), len(self.completed_queries), 1)
        done_q = len(self.completed_queries)
        live_calls = self.cache.session_fast_flights_calls + self.cache.session_serpapi_calls
        payload: dict[str, Any] = {
            "phase": phase,
            "current_query": current_query,
            "queries_completed": done_q,
            "queries_total": total_q,
            "schedule_index": self.schedule_index,
            "schedules_total": self.schedules_total,
            "schedule_route": self.current_schedule_route,
            "strategy_label": self.current_strategy_label,
            "strategies_completed": self.strategies_completed,
            "strategies_total": self.strategies_total,
            "cache_hits": self.cache.session_hits,
            "cache_misses": self.cache.session_misses,
            "live_calls": live_calls,
            "progress_pct": progress_pct if progress_pct is not None else self.compute_progress_pct(),
        }
        if last_query is not None:
            payload["last_query"] = last_query
        self.progress_callback(payload)

    def search(self, query: LegSearch) -> SearchResult:
        if query in self._run_results:
            return self._run_results[query]

        query_label = self.format_query_label(query)
        self.planned_queries.add(query)
        self.emit_progress(phase="query_start", current_query=query_label)

        hits_before = self.cache.session_hits
        if self.delegate.is_simulation():
            results = self.delegate.search(query)
        else:
            cached = (
                None if self.force_refresh else self.cache.get_leg_options(query, provider_scope=self._provider_scope)
            )
            if cached is not None:
                results = SearchResult(options=tuple(cached))
            else:
                if self.force_refresh:
                    self.cache.session_misses += 1
                results = self.delegate.search(query)
                self.cache.store_leg_options(query, results, provider_scope=self._provider_scope)

        self._run_results[query] = results
        self.search_issues.extend(results.issues)
        self.completed_queries.add(query)
        source = (
            "simulated"
            if self.delegate.is_simulation()
            else ("cache" if self.cache.session_hits > hits_before else "live")
        )
        self.emit_progress(
            phase="query_done",
            current_query=query_label,
            last_query={
                "query": query_label,
                "route": f"{', '.join(query.origins)} → {', '.join(query.destinations)}",
                "date": query.departure_date.isoformat(),
                "cabin": query.cabin.value.replace("_", " ").title(),
                "options_count": len(results.options),
                "status": results.status.value,
                "source": source,
            },
        )
        return results
