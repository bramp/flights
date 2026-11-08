"""Verify that schema documentation is runnable and appears in the API."""

from __future__ import annotations

import doctest

from backend.app.main import create_app
from backend.app.models import schemas


def test_schema_documentation_examples() -> None:
    result = doctest.testmod(schemas)
    assert result.attempted > 0
    assert result.failed == 0


def test_openapi_documents_schema_fields() -> None:
    components = create_app().openapi()["components"]["schemas"]
    models = (
        "BaggageConfig",
        "CabinPolicy",
        "StopsPolicy",
        "OptimizationWeights",
        "CityStopSpec",
        "TripRequest",
        "FlightSegment",
        "FlightLegOption",
        "FareEstimate",
        "BookedTicket",
        "ScheduledStopVisit",
        "EvaluatedItinerary",
        "CacheStats",
        "OptimizationResponse",
    )
    for model_name in models:
        schema = components[model_name]
        assert schema.get("description"), model_name
        for field_name, field in schema["properties"].items():
            assert field.get("description"), f"{model_name}.{field_name}"

    enums = (
        "CabinClass",
        "ConcreteCabinClass",
        "StopsMode",
        "ConcreteStopsMode",
        "TicketType",
        "StrategyKind",
        "ProviderMode",
        "FareProvenance",
    )
    for enum_name in enums:
        assert components[enum_name].get("description"), enum_name
