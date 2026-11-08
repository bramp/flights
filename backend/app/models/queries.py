"""Request and outcome models for flight-leg searches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from backend.app.models.schemas import ConcreteCabinClass, FlightLegOption


@dataclass(frozen=True)
class LegSearch:
    """Describe a flight-leg search across origin and destination airports.

    Airport codes are stripped, converted to uppercase, and deduplicated
    within each tuple. Blank codes are removed. Codes retain the order of
    their first occurrence, preserving airport priority. This model does not
    check whether the codes identify real airports.

    Attributes:
        origins: Origin airport codes in priority order.
        destinations: Destination airport codes in priority order.
        departure_date: Departure date for the requested leg.
        cabin: Requested cabin class.

    Raises:
        ValueError: If either origins or destinations is empty after normalization.

    Examples:
        >>> from datetime import date
        >>> from backend.app.models.queries import LegSearch
        >>> from backend.app.models.schemas import ConcreteCabinClass
        >>> query = LegSearch(
        ...     origins=(" sfo ", "SFO", "OAK"),
        ...     destinations=("lhr", "LGW", " lhr "),
        ...     departure_date=date(2026, 11, 10),
        ...     cabin=ConcreteCabinClass.BUSINESS,
        ... )
        >>> query.origins
        ('SFO', 'OAK')
        >>> query.destinations
        ('LHR', 'LGW')
    """

    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    departure_date: date
    cabin: ConcreteCabinClass

    def __post_init__(self) -> None:
        """Normalize codes and require at least one origin and destination."""
        origins = tuple(dict.fromkeys(code.strip().upper() for code in self.origins if code.strip()))
        destinations = tuple(dict.fromkeys(code.strip().upper() for code in self.destinations if code.strip()))
        if not origins or not destinations:
            raise ValueError("A flight search requires at least one origin and destination airport.")
        object.__setattr__(self, "origins", origins)
        object.__setattr__(self, "destinations", destinations)

    @classmethod
    def single(cls, origin: str, destination: str, departure_date: date, cabin: ConcreteCabinClass) -> LegSearch:
        """Create a search for one origin and one destination.

        The airport codes use the same normalization as other leg searches.

        Raises:
            ValueError: If either airport code is blank after stripping whitespace.

        Examples:
            >>> from datetime import date
            >>> from backend.app.models.queries import LegSearch
            >>> from backend.app.models.schemas import ConcreteCabinClass
            >>> query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.ECONOMY)
            >>> query.origins, query.destinations
            (('SFO',), ('LHR',))
        """
        return cls((origin,), (destination,), departure_date, cabin)


class SearchStatus(StrEnum):
    """Describe how much of a flight search completed.

    Attributes:
        COMPLETE: The search completed; it may still report issues.
        PARTIAL: The search did not fully complete and may have no options.
        FAILED: The search failed and cannot contain options.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class SearchIssueKind(StrEnum):
    """Classify an issue encountered during a flight search.

    Attributes:
        PROVIDER_ERROR: A provider request or response failed.
        BUDGET_EXHAUSTED: The live-query budget prevented further searches.
        MISSING_CREDENTIALS: A selected provider lacked required credentials.
        TRUNCATED: Some requested airport pairs were not searched.
    """

    PROVIDER_ERROR = "provider_error"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MISSING_CREDENTIALS = "missing_credentials"
    TRUNCATED = "truncated"


@dataclass(frozen=True)
class SearchIssue:
    """Describe an issue encountered during a flight search.

    Attributes:
        kind: Category of the issue.
        message: Human-readable details about the issue.

    Examples:
        >>> from backend.app.models.queries import SearchIssue, SearchIssueKind
        >>> issue = SearchIssue(SearchIssueKind.PROVIDER_ERROR, "The provider request failed.")
        >>> issue.kind.value
        'provider_error'
    """

    kind: SearchIssueKind
    message: str


@dataclass(frozen=True)
class SearchResult:
    """Report flight-leg options and the status of a search.

    A complete search may have no options and may still report issues, such
    as a recovered provider error. A partial search may also have no options.
    The result's fields cannot be reassigned, but its flight options may be
    mutable.

    Attributes:
        options: Candidate flight-leg options, in the order supplied.
        status: Completion status, which defaults to ``COMPLETE``.
        issues: Problems reported during the search, empty by default.

    Raises:
        ValueError: If an incomplete result has no issues or a failed result
            contains options.

    Examples:
        >>> from backend.app.models.queries import SearchIssue, SearchIssueKind, SearchResult, SearchStatus
        >>> SearchResult().status.value
        'complete'
        >>> issue = SearchIssue(SearchIssueKind.BUDGET_EXHAUSTED, "Live-query limit reached.")
        >>> result = SearchResult(status=SearchStatus.PARTIAL, issues=(issue,))
        >>> result.status.value, result.options
        ('partial', ())
    """

    options: tuple[FlightLegOption, ...] = ()
    status: SearchStatus = SearchStatus.COMPLETE
    issues: tuple[SearchIssue, ...] = ()

    def __post_init__(self) -> None:
        """Reject incomplete results without issues and failed results with options."""
        if self.status != SearchStatus.COMPLETE and not self.issues:
            raise ValueError("An incomplete flight search must report an issue.")
        if self.status == SearchStatus.FAILED and self.options:
            raise ValueError("A failed flight search cannot contain options.")
