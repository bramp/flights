# AGENTS.md — AI Coding Agent Guidelines

## Project Overview
This repository implements **FareSplit**, the multi-city flight schedule and ticket-partitioning optimizer described in [DESIGN.md](DESIGN.md).
See [DEVELOPER.md](DEVELOPER.md) for the directory structure and development commands, and [README.md](README.md) for user-facing behavior.

## Coding Standards & Best Practices
1. **Strict Type Annotations:** Use Python 3.12+ type syntax (`list[str]`, `dict[str, Any]`, `X | None`) across all functions and classes.
2. **Pure Solver Logic:** Keep solver algorithms (`route_dag.py`, `hub_splitter.py`, `partitioner.py`, `pareto.py`, `optimizer.py`) decoupled from HTTP/FastAPI concerns and unit-tested.
3. **Cache-First Discipline:** Every external flight or multi-slice quote lookup must go through `CachedFlightProvider` / `FlightCache` (`sqlite_cache.py`).
4. **No Hidden-City Ticketing:** Never generate throwaway or hidden-city tickets; every leg of every booked ticket must be flown in sequence by the passenger.
5. **Git Hygiene:**
   - Never run `git add .` — always stage explicit files relevant to the change.
   - Do not commit unless explicitly requested by the user.
6. **Verification & Formatting:** Always run `uv run ruff format .`, `uv run ruff check .`, `node --check backend/app/static/app.js`, and `uv run pytest` after making code changes (also enforced automatically via `.pre-commit-config.yaml`).

## Documentation Style
- Follow PEP 257 docstring conventions and use Google-style sections where useful.
- Write clear technical English inspired by ASD-STE100; do not claim formal compliance. Prefer short sentences, active voice, and consistent terminology. Avoid idioms and ambiguous pronouns.
- Document public modules, classes, and functions. Document private helpers when their behavior or constraints are not obvious.
- Start function docstrings with an imperative summary ending in a period, such as `Return the cheapest valid ticket partition.` Separate additional details from the summary with a blank line.
- Add `Args`, `Returns`, `Yields`, and `Raises` sections only when applicable. Explain meaning and constraints; do not repeat type annotations.
- Document contracts such as units, time zones, boundary inclusivity, ordering, mutation, side effects, and expected exceptions.
- For solver code, explain feasibility constraints, assumptions, pruning rules, and whether results are exact or approximate.
- Use established domain terms consistently. Distinguish flight segments, itinerary legs, tickets, and ticket partitions.
- For Pydantic models, use `Field` descriptions for externally visible field semantics and constraints so API documentation includes them.
- Use inline comments for non-obvious reasoning, not narration. Keep implementation details out of public API contracts.
- Update affected docstrings and user or developer documentation when behavior changes. Keep examples deterministic and testable.
- Apply these rules to new or modified code; avoid unrelated documentation-only rewrites.
