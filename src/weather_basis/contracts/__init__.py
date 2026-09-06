"""Immutable CME contract definitions and pure payoff/index helpers."""

from .calendar import PAIRS, STRIPS, Pair, Strip, as_of, fit_through, season_of, settlement_date
from .degree_days import daily_cdd, daily_hdd, monthly_index
from .payoff import call, futures, put
from .registry import ContractRegistry, load_contract_registry, load_frozen_vintage
from .universe import Station, load_universe
from .windows import ContractWindow, next_contract_year, resolve_contract_window

__all__ = [
    "PAIRS",
    "STRIPS",
    "Pair",
    "ContractRegistry",
    "ContractWindow",
    "Station",
    "Strip",
    "as_of",
    "call",
    "daily_cdd",
    "daily_hdd",
    "fit_through",
    "futures",
    "load_universe",
    "load_contract_registry",
    "load_frozen_vintage",
    "monthly_index",
    "next_contract_year",
    "put",
    "season_of",
    "settlement_date",
    "resolve_contract_window",
]
