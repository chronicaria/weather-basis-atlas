"""CME monthly temperature-contract calendar (plan Sections 5.2 and D-32/D-66)."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, order=True)
class Pair:
    """One listed monthly degree-day index, identified by index type and month."""

    index: str
    month: int

    def __post_init__(self) -> None:
        if self.index not in {"HDD", "CDD"}:
            raise ValueError("index must be HDD or CDD")
        if not 1 <= self.month <= 12:
            raise ValueError("month must be in 1..12")

    @property
    def key(self) -> str:
        return f"{self.index}-{self.month:02d}"

    @property
    def label(self) -> str:
        return self.key


# The ordering is contractual: HDD Oct--Apr, then CDD Apr--Oct.
PAIRS: tuple[Pair, ...] = tuple(
    [Pair("HDD", month) for month in (10, 11, 12, 1, 2, 3, 4)]
    + [Pair("CDD", month) for month in (4, 5, 6, 7, 8, 9, 10)]
)


@dataclass(frozen=True)
class Strip:
    """A listed seasonal strip, expressed as a sum of monthly indexes."""

    code: str
    index: str
    first_month: int
    last_month: int

    @property
    def months(self) -> tuple[int, ...]:
        if self.first_month <= self.last_month:
            return tuple(range(self.first_month, self.last_month + 1))
        return tuple(range(self.first_month, 13)) + tuple(range(1, self.last_month + 1))


STRIPS: tuple[Strip, ...] = (
    Strip("X", "HDD", 11, 3),
    Strip("Z", "HDD", 12, 2),
    Strip("Q1", "HDD", 1, 3),
    Strip("Q4", "HDD", 10, 12),
    Strip("K", "CDD", 5, 9),
    Strip("N", "CDD", 7, 8),
    Strip("Q2", "CDD", 4, 6),
    Strip("Q3", "CDD", 7, 9),
)


def _require_listed(pair: Pair) -> None:
    if pair not in PAIRS:
        raise ValueError(f"{pair.key} is not a listed CME monthly temperature pair")


def season_of(pair: Pair, year: int, month: int) -> int | None:
    """Return the contract season for a matching calendar month, else ``None``."""
    _require_listed(pair)
    return year if month == pair.month else None


def as_of(pair: Pair, season: int) -> date:
    """First day of the calendar month before the contract month."""
    _require_listed(pair)
    previous_month = pair.month - 1 or 12
    year = season if pair.month > 1 else season - 1
    return date(year, previous_month, 1)


def fit_through(pair: Pair, season: int) -> date:
    """Last day of the calendar month two months before the contract month."""
    _require_listed(pair)
    as_of_date = as_of(pair, season)
    return as_of_date - timedelta(days=1)


def settlement_date(pair: Pair, season: int) -> date:
    """Second weekday after the contract window; exchange holidays are intentionally ignored."""
    _require_listed(pair)
    window_end = date(season, pair.month, monthrange(season, pair.month)[1])
    cursor = window_end
    weekdays = 0
    while weekdays < 2:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            weekdays += 1
    return cursor
