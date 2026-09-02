"""Immutable CME contract definitions and pure payoff/index helpers."""

from .calendar import PAIRS, STRIPS, Pair, Strip, as_of, fit_through, season_of, settlement_date
from .degree_days import daily_cdd, daily_hdd, monthly_index
from .payoff import call, futures, put
from .universe import Station, load_universe

__all__ = [
    "PAIRS",
    "STRIPS",
    "Pair",
    "Station",
    "Strip",
    "as_of",
    "call",
    "daily_cdd",
    "daily_hdd",
    "fit_through",
    "futures",
    "load_universe",
    "monthly_index",
    "put",
    "season_of",
    "settlement_date",
]
