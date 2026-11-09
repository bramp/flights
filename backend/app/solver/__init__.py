"""Generate schedule candidates and compare ticket-partition strategies.

The solver samples schedules and estimates fares; its results are not a proof
of a globally optimal or bookable trip. Live flight searches must pass through
``CachedFlightProvider``.
"""
