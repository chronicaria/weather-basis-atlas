"""Transparent, global-horizon weather scenario baselines.

The functions in this module deliberately accept a small daily panel rather
than opening the national panel.  Platform code supplies location chunks; the
same ``CommonScenarioPlan`` is used for every chunk so a county request never
reseeds weather paths.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from weather_basis.contracts.calendar import PAIRS, Pair
from weather_basis.contracts.degree_days import daily_cdd, daily_hdd
from weather_basis.provenance.ids import content_id
from weather_basis.schemas.scenarios import ScenarioMatrix, ScenarioSet


def _dates(value: np.ndarray | pd.DatetimeIndex) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(value))
    if result.is_monotonic_increasing is False or result.has_duplicates:
        raise ValueError("daily dates must be increasing and unique")
    return result


def _daily(values: np.ndarray, dates: pd.DatetimeIndex, locations: tuple[str, ...]) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 2 or result.shape != (len(dates), len(locations)):
        raise ValueError("daily values must have shape (dates, locations)")
    return result


def _location_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize NumPy string labels at the public panel boundary."""
    result = tuple(str(value) for value in values)
    if not result or len(result) != len(set(result)):
        raise ValueError("location ids must be nonempty and unique")
    return result


@dataclass(frozen=True, kw_only=True)
class CommonScenarioPlan:
    """Scientific identity for one July--June common weather horizon."""

    valuation_asof: str
    horizon_start: str
    horizon_end: str
    scenario_count: int
    seed: int
    generator_spec_id: str = "common-year-trend-bootstrap-v1"
    calendar_id: str = "gregorian-local-observation-date"
    base_f: float = 65.0
    location_universe_id: str = "explicit-location-universe-required"

    def __post_init__(self) -> None:
        start, end = pd.Timestamp(self.horizon_start), pd.Timestamp(self.horizon_end)
        if start > end or self.scenario_count < 1:
            raise ValueError("plan needs a nonempty horizon and positive scenario count")
        if start.day != 1 or start.month != 7 or (end.month, end.day) != (6, 30):
            raise ValueError("V2 public plan must be a complete July--June horizon")
        if pd.Timestamp(self.valuation_asof) > start:
            raise ValueError("valuation as-of cannot be after scenario horizon begins")

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.date_range(self.horizon_start, self.horizon_end, freq="D")

    @property
    def plan_id(self) -> str:
        return content_id(
            {
                "valuation_asof": self.valuation_asof,
                "horizon_start": self.horizon_start,
                "horizon_end": self.horizon_end,
                # Path count selects a prefix of the release-wide draw plan;
                # it is not a scientific source-plan input.  Excluding it lets
                # public scenario IDs be the exact offline-ID prefix.
                "seed": self.seed,
                "generator_spec_id": self.generator_spec_id,
                "calendar_id": self.calendar_id,
                "base_f": self.base_f,
                "location_universe_id": self.location_universe_id,
            }
        )


@dataclass(frozen=True)
class DailyScenarioPaths:
    scenario_set: ScenarioSet
    dates: pd.DatetimeIndex
    location_ids: tuple[str, ...]
    values: np.ndarray  # scenario, day, location

    def __post_init__(self) -> None:
        array = np.array(self.values, dtype=np.float64, copy=True)
        if array.shape != (
            len(self.scenario_set.scenario_ids),
            len(self.dates),
            len(self.location_ids),
        ):
            raise ValueError("daily scenario path shape mismatch")
        if not np.all(np.isfinite(array)):
            raise ValueError("daily paths require complete common support")
        array.flags.writeable = False
        object.__setattr__(self, "values", array)


def _scenario_set(
    plan: CommonScenarioPlan,
    *,
    scenario_ids: tuple[str, ...],
    location_ids: tuple[str, ...],
    scenario_type: str,
    data_vintage_id: str,
    model_spec_ids: tuple[str, ...],
    identity_inputs: object | None = None,
) -> ScenarioSet:
    return ScenarioSet(
        scenario_set_id=content_id(
            {
                "plan": plan.plan_id,
                "scenario_ids": scenario_ids,
                "location_universe_id": plan.location_universe_id,
                "type": scenario_type,
                "identity_inputs": identity_inputs,
            }
        ),
        scenario_type=scenario_type,
        scenario_ids=scenario_ids,
        probability_weights=tuple([1.0 / len(scenario_ids)] * len(scenario_ids)),
        calendar_id=plan.calendar_id,
        date_start=plan.horizon_start,
        date_end=plan.horizon_end,
        location_ids=location_ids,
        generator_spec_id=plan.generator_spec_id,
        common_random_plan_id=plan.plan_id,
        data_vintage_id=data_vintage_id,
        model_spec_ids=model_spec_ids,
        valuation_asof=plan.valuation_asof,
        scenario_id_hash=content_id(list(scenario_ids)),
    )


def _annual_windows(dates: pd.DatetimeIndex) -> dict[int, np.ndarray]:
    # Season label is the June year, matching a July--June public horizon.
    labels = np.where(dates.month >= 7, dates.year + 1, dates.year)
    return {int(year): np.flatnonzero(labels == year) for year in np.unique(labels)}


def build_historical_common_years(
    *,
    dates: np.ndarray | pd.DatetimeIndex,
    values: np.ndarray,
    location_ids: tuple[str, ...],
    plan: CommonScenarioPlan,
    data_vintage_id: str,
) -> DailyScenarioPaths:
    """Observed common July--June seasons with no resampling or trend shift."""
    location_ids = _location_ids(location_ids)
    history_dates = _dates(dates)
    daily = _daily(values, history_dates, location_ids)
    target_length = len(plan.dates)
    retained: list[np.ndarray] = []
    ids: list[str] = []
    cutoff = pd.Timestamp(plan.valuation_asof)
    for season, rows in _annual_windows(history_dates).items():
        if not np.all(history_dates[rows] < cutoff):
            continue
        if len(rows) != target_length or not np.all(np.isfinite(daily[rows])):
            continue
        # Calendar position, including leap-day status, must match the target.
        if tuple(history_dates[rows].strftime("%m-%d")) != tuple(plan.dates.strftime("%m-%d")):
            continue
        retained.append(daily[rows])
        ids.append(f"historical-{season}")
    if not retained:
        raise ValueError("no complete common observed seasons for the requested horizon")
    paths = np.stack(retained, axis=0)
    scenario_ids = tuple(ids)
    scenario_set = _scenario_set(
        plan,
        scenario_ids=scenario_ids,
        location_ids=location_ids,
        scenario_type="historical",
        data_vintage_id=data_vintage_id,
        model_spec_ids=("observed-common-year-v1",),
    )
    return DailyScenarioPaths(
        scenario_set=scenario_set, dates=plan.dates, location_ids=location_ids, values=paths
    )


def _global_block_rows(
    valid: np.ndarray, n_days: int, rng: np.random.Generator, mean_block: int
) -> np.ndarray:
    candidates = np.flatnonzero(valid)
    if candidates.size < n_days:
        raise ValueError("insufficient complete daily support for global bootstrap")
    result: list[int] = []
    while len(result) < n_days:
        start = int(rng.integers(0, candidates.size))
        length = min(int(rng.geometric(1.0 / mean_block)), n_days - len(result))
        result.extend(candidates[(start + np.arange(length)) % candidates.size].tolist())
    return np.asarray(result, dtype=np.int64)


def build_trend_bootstrap(
    *,
    dates: np.ndarray | pd.DatetimeIndex,
    values: np.ndarray,
    location_ids: tuple[str, ...],
    plan: CommonScenarioPlan,
    data_vintage_id: str,
    mean_block_days: int = 7,
    source_seasons: tuple[int, ...] | None = None,
    exact_drawn_seasons: tuple[int, ...] | None = None,
) -> DailyScenarioPaths:
    """Shared moving-block daily bootstrap with a transparent linear trend shift.

    Every location uses one whole observed July--June season per path.  This
    preserves the calendar and within-season dependence; it is predictive,
    never an observed replay.  ``source_seasons`` is the release-wide support
    chosen by the compute owner and must be reused for every location chunk.
    """
    history_dates = _dates(dates)
    location_ids = _location_ids(location_ids)
    daily = _daily(values, history_dates, location_ids)
    del mean_block_days  # retained API field; v1 uses whole common seasons.
    cutoff = pd.Timestamp(plan.valuation_asof)
    allowed = history_dates < cutoff
    candidates: dict[int, np.ndarray] = {}
    for season, rows in _annual_windows(history_dates).items():
        if not np.all(allowed[rows]) or len(rows) != len(plan.dates):
            continue
        if tuple(history_dates[rows].strftime("%m-%d")) != tuple(plan.dates.strftime("%m-%d")):
            continue
        if np.all(np.isfinite(daily[rows])):
            candidates[season] = rows
    selected_seasons = tuple(source_seasons or tuple(sorted(candidates)))
    if not selected_seasons or not set(selected_seasons) <= set(candidates):
        raise ValueError("declared global source seasons lack complete common support")
    years = np.asarray(sorted(candidates), dtype=float)
    season_means = np.asarray([daily[candidates[int(year)]].mean(axis=0) for year in years])
    target_year = (pd.Timestamp(plan.horizon_start).year + pd.Timestamp(plan.horizon_end).year) / 2
    slopes = np.empty(len(location_ids), dtype=float)
    for col in range(len(location_ids)):
        slopes[col] = np.polyfit(years, season_means[:, col], 1)[0] if len(years) >= 2 else 0.0
    if exact_drawn_seasons is None:
        rng = np.random.default_rng(plan.seed)
        drawn = rng.choice(np.asarray(selected_seasons), size=plan.scenario_count, replace=True)
    else:
        drawn = np.asarray(exact_drawn_seasons, dtype=int)
        if drawn.shape != (plan.scenario_count,) or not set(drawn) <= set(selected_seasons):
            raise ValueError("exact drawn seasons must match plan count and declared support")
    paths = np.stack(
        [
            daily[candidates[int(season)]] + slopes * (target_year - float(season))
            for season in drawn
        ],
        axis=0,
    )
    scenario_ids = tuple(
        f"{plan.plan_id[:12]}-season-{int(season)}-{index:05d}"
        for index, season in enumerate(drawn)
    )
    scenario_set = _scenario_set(
        plan,
        scenario_ids=scenario_ids,
        location_ids=location_ids,
        scenario_type="physical_predictive",
        data_vintage_id=data_vintage_id,
        model_spec_ids=("common-year-trend-bootstrap-v1",),
        identity_inputs={
            "source_seasons": tuple(int(item) for item in drawn),
            "eligible_seasons": selected_seasons,
            "location_universe_id": plan.location_universe_id,
        },
    )
    return DailyScenarioPaths(
        scenario_set=scenario_set, dates=plan.dates, location_ids=location_ids, values=paths
    )


def monthly_degree_day_matrix(
    paths: DailyScenarioPaths, *, pairs: tuple[Pair, ...] = PAIRS
) -> ScenarioMatrix:
    """Reduce daily common paths to a compact matrix for every declared pair."""
    entities: list[str] = []
    columns: list[np.ndarray] = []
    for pair in pairs:
        mask = paths.dates.month.to_numpy() == pair.month
        if not np.any(mask):
            raise ValueError(f"{pair.key} is outside this scenario horizon")
        transformed = (
            daily_hdd(paths.values[:, mask, :], base=65.0)
            if pair.index == "HDD"
            else daily_cdd(paths.values[:, mask, :], base=65.0)
        )
        monthly = transformed.sum(axis=1, dtype=np.float64)
        for column, location in enumerate(paths.location_ids):
            entities.append(f"{location}:{pair.key}")
            columns.append(monthly[:, column])
    return ScenarioMatrix(
        parent_scenario_set_id=paths.scenario_set.scenario_set_id,
        scenario_ids=paths.scenario_set.scenario_ids,
        entity_ids=tuple(entities),
        values=np.column_stack(columns),
        units="degree_days",
    )
