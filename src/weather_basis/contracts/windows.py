"""Explicit research contract windows.

The V1 calendar helper is retained for historical compatibility.  This module
does not turn its weekday approximation into an exchange-settlement claim.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from weather_basis.schemas.contracts import ContractWindow

from .calendar import Pair, settlement_date


def next_contract_year(pair: Pair, valuation_date: date) -> int:
    """Return the next contract month on or after ``valuation_date``.

    A month that is already complete is not silently selected as the current
    contract.  Thus a July 1 request for June resolves to next June.
    """

    if pair.month < valuation_date.month:
        return valuation_date.year + 1
    return valuation_date.year


def resolve_contract_window(
    pair: Pair,
    valuation_date: date,
    *,
    contract_year: int | None = None,
    require_exact_settlement: bool = False,
) -> ContractWindow:
    """Resolve a monthly window without inventing exchange holiday handling.

    ``valuation_date`` is interpreted at the start of its local calendar day:
    during a contract month, days before it are observed and the valuation day
    and later days remain.  Callers with an intraday observation cutoff must
    supply a more specific observation record rather than alter this boundary.
    """

    if require_exact_settlement:
        raise ValueError(
            "exact settlement timing is unavailable: no versioned exchange-business-day "
            "calendar is retained in the frozen V1 inputs"
        )
    year = next_contract_year(pair, valuation_date) if contract_year is None else contract_year
    if not 1900 <= year <= 9999:
        raise ValueError("contract_year must be a four-digit calendar year")
    start = date(year, pair.month, 1)
    end = date(year, pair.month, monthrange(year, pair.month)[1])
    if valuation_date < start:
        status = "future"
        observed_start = observed_end = None
        remaining_start, remaining_end = start, end
    elif valuation_date > end:
        status = "elapsed"
        observed_start, observed_end = start, end
        remaining_start = remaining_end = None
    else:
        status = "partial"
        observed_start = start if valuation_date > start else None
        observed_end = valuation_date - timedelta(days=1) if valuation_date > start else None
        remaining_start, remaining_end = valuation_date, end

    return ContractWindow(
        contract_window_id=f"v2:{pair.key}:{year}",
        contract_year=year,
        index=pair.index,
        month=pair.month,
        observation_start=start.isoformat(),
        observation_end=end.isoformat(),
        valuation_date=valuation_date.isoformat(),
        timing_status=status,
        observed_start=observed_start.isoformat() if observed_start else None,
        observed_end=observed_end.isoformat() if observed_end else None,
        remaining_start=remaining_start.isoformat() if remaining_start else None,
        remaining_end=remaining_end.isoformat() if remaining_end else None,
        research_settlement_date=settlement_date(pair, year).isoformat(),
        settlement_timing_status="approximate_research_only",
        exact_settlement_available=False,
        exact_settlement_unavailable_reason=(
            "Frozen V1 only retains a second-weekday approximation; exchange holidays and "
            "a versioned exchange-business-day calendar are absent."
        ),
    )
