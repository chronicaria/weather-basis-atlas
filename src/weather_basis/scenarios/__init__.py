"""Common-horizon scenario generation and aligned monthly matrix storage."""

from .artifacts import DEFAULT_REPRESENTATIVE_COUNTIES, build_from_frozen, build_national
from .common import (
    CommonScenarioPlan,
    DailyScenarioPaths,
    build_historical_common_years,
    build_trend_bootstrap,
    monthly_degree_day_matrix,
)
from .diagnostics import dependence_diagnostics, marginal_diagnostics
from .global_plan import GlobalSeasonPlan, build_global_season_plan
from .marginal import RankCoupledMarginalResult, rank_coupled_marginals
from .r04 import run_r04_pilot
from .r2j import R2JCommonHorizonAdapter, r2j_common_horizon
from .r2j_production import build_r2j_production, prepare_r2j_fit, r2j_raw_residual_horizon
from .store import LazyMonthlyScenarioStore

__all__ = [
    "CommonScenarioPlan",
    "DailyScenarioPaths",
    "LazyMonthlyScenarioStore",
    "R2JCommonHorizonAdapter",
    "RankCoupledMarginalResult",
    "build_historical_common_years",
    "build_trend_bootstrap",
    "monthly_degree_day_matrix",
    "r2j_common_horizon",
    "build_r2j_production",
    "prepare_r2j_fit",
    "r2j_raw_residual_horizon",
    "rank_coupled_marginals",
    "marginal_diagnostics",
    "dependence_diagnostics",
    "DEFAULT_REPRESENTATIVE_COUNTIES",
    "build_from_frozen",
    "build_national",
    "GlobalSeasonPlan",
    "build_global_season_plan",
    "run_r04_pilot",
]
