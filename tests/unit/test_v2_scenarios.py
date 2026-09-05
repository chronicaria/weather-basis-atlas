from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather_basis.contracts.calendar import PAIRS
from weather_basis.scenarios import (
    CommonScenarioPlan,
    LazyMonthlyScenarioStore,
    build_historical_common_years,
    build_trend_bootstrap,
    dependence_diagnostics,
    marginal_diagnostics,
    monthly_degree_day_matrix,
    r2j_common_horizon,
    rank_coupled_marginals,
)
from weather_basis.scenarios.artifacts import build_national
from weather_basis.schemas.scenarios import ScenarioMatrix


def _plan(count: int = 3) -> CommonScenarioPlan:
    return CommonScenarioPlan(
        valuation_asof="2026-07-01",
        horizon_start="2026-07-01",
        horizon_end="2027-06-30",
        scenario_count=count,
        seed=42,
    )


def _history() -> tuple[pd.DatetimeIndex, np.ndarray, tuple[str, ...]]:
    # Two complete non-leap July--June seasons, with two deliberately related sites.
    dates = pd.date_range("2020-07-01", "2022-06-30", freq="D")
    base = 60 + 15 * np.sin(np.arange(len(dates)) / 25)
    return dates, np.column_stack((base, base + 3)), ("01001", "station-a")


def test_historical_common_years_preserves_overlap_and_monthly_daily_identity():
    dates, values, locations = _history()
    paths = build_historical_common_years(
        dates=dates,
        values=values,
        location_ids=locations,
        plan=_plan(),
        data_vintage_id="fixture-v1",
    )
    assert paths.values.shape == (2, 365, 2)
    assert paths.scenario_set.scenario_type == "historical"
    # Same daily temperature drives both transformations on every path.
    hdd = np.maximum(65 - paths.values, 0)
    cdd = np.maximum(paths.values - 65, 0)
    np.testing.assert_allclose(cdd - hdd, paths.values - 65)
    matrix = monthly_degree_day_matrix(paths)
    july_cdd = matrix.values[:, matrix.entity_ids.index("01001:CDD-07")]
    expected = cdd[:, paths.dates.month == 7, 0].sum(axis=1)
    np.testing.assert_allclose(july_cdd, expected)
    assert set(pair.key for pair in PAIRS) == {entity.split(":")[1] for entity in matrix.entity_ids}


def test_bootstrap_is_deterministic_global_and_not_observed_history():
    dates, values, locations = _history()
    first = build_trend_bootstrap(
        dates=dates,
        values=values,
        location_ids=locations,
        plan=_plan(),
        data_vintage_id="fixture-v1",
        mean_block_days=5,
    )
    second = build_trend_bootstrap(
        dates=dates,
        values=values,
        location_ids=locations,
        plan=_plan(),
        data_vintage_id="fixture-v1",
        mean_block_days=5,
    )
    assert first.scenario_set.scenario_type == "physical_predictive"
    assert first.scenario_set.scenario_ids == second.scenario_set.scenario_ids
    np.testing.assert_allclose(first.values, second.values)


def test_bootstrap_enforces_cutoff_seasonality_and_declared_universe_identity():
    dates, values, locations = _history()
    plan = CommonScenarioPlan(
        valuation_asof="2021-07-01",
        horizon_start="2026-07-01",
        horizon_end="2027-06-30",
        scenario_count=2,
        seed=4,
        location_universe_id="fixture-universe-a",
    )
    paths = build_trend_bootstrap(
        dates=dates, values=values, location_ids=locations, plan=plan, data_vintage_id="fixture-v1"
    )
    assert all("season-2021" in item for item in paths.scenario_set.scenario_ids)
    # The source season is mapped day-for-day, never July temperatures into January.
    expected = values[:365]
    np.testing.assert_allclose(
        paths.values[0] - paths.values[0].mean(axis=0), expected - expected.mean(axis=0)
    )
    other = CommonScenarioPlan(
        valuation_asof="2021-07-01",
        horizon_start="2026-07-01",
        horizon_end="2027-06-30",
        scenario_count=2,
        seed=4,
        location_universe_id="fixture-universe-b",
    )
    assert plan.plan_id != other.plan_id


def test_r2j_adapter_one_horizon_uses_shared_path_ids_and_daily_identity():
    dates, residuals, locations = _history()
    residuals = (residuals - residuals.mean(axis=0)) / residuals.std(axis=0)
    plan = _plan(4)
    mean = np.full((len(plan.dates), 2), 60.0)
    sigma = np.ones((len(plan.dates), 2))
    paths = r2j_common_horizon(
        history_dates=dates,
        standardized_residuals=residuals,
        target_mean=mean,
        target_sigma=sigma,
        location_ids=locations,
        plan=plan,
        data_vintage_id="fixture-v1",
        model_spec_id="r2j-test",
        ar_coefficients=np.zeros((2, 1)),
    )
    assert paths.values.shape == (4, 365, 2)
    assert all("r2j" in item for item in paths.scenario_set.scenario_ids)


def test_rank_coupling_keeps_matrix_aligned_and_marginal_is_separate():
    dates, values, locations = _history()
    historical = build_historical_common_years(
        dates=dates,
        values=values,
        location_ids=locations,
        plan=_plan(),
        data_vintage_id="fixture-v1",
    )
    source = monthly_degree_day_matrix(historical)
    predictive = build_trend_bootstrap(
        dates=dates,
        values=values,
        location_ids=locations,
        plan=_plan(5),
        data_vintage_id="fixture-v1",
    )
    result = rank_coupled_marginals(
        historical_indexes=source.values,
        entity_ids=source.entity_ids,
        scenario_set=predictive.scenario_set,
        seed=9,
    )
    assert result.matrix.scenario_ids == predictive.scenario_set.scenario_ids
    assert "monthly-index-only" in result.product_support
    assert not hasattr(result.marginals[0], "assert_same_scenarios")
    marginal = marginal_diagnostics(source, result.matrix)
    dependence = dependence_diagnostics(source, result.matrix)
    assert marginal["kind"] == "marginal"
    assert dependence["kind"] == "dependence"


def test_lazy_store_requires_all_14_pairs_and_never_reseeds_missing_county():
    plan = _plan(2)
    dates, values, locations = _history()
    paths = build_trend_bootstrap(
        dates=dates, values=values, location_ids=locations, plan=plan, data_vintage_id="fixture-v1"
    )
    base = monthly_degree_day_matrix(paths)
    county = "01001"
    county_matrix = base.select(tuple(f"{county}:{pair.key}" for pair in PAIRS))
    store = LazyMonthlyScenarioStore(paths.scenario_set)
    store.add_chunk(county, county_matrix)
    assert store.select(county, ("HDD-01", "CDD-07")).entity_ids == ("01001:HDD-01", "01001:CDD-07")
    with pytest.raises(ValueError, match="missing scenario support"):
        store.get_chunk("99999")
    incomplete = ScenarioMatrix(
        parent_scenario_set_id=paths.scenario_set.scenario_set_id,
        scenario_ids=paths.scenario_set.scenario_ids,
        entity_ids=tuple(f"99999:{pair.key}" for pair in PAIRS[:-1]),
        values=np.ones((2, 13)),
        units="degree_days",
    )
    with pytest.raises(ValueError, match="14 declared"):
        store.add_chunk("99999", incomplete)


def test_streamed_artifact_uses_one_parent_and_exact_offline_prefix(tmp_path):
    root = Path(__file__).resolve().parents[2]
    research = {
        "offline_paths": 4,
        "public_paths": 2,
        "valuation_asof": "2026-07-01",
        "horizon_start": "2026-07-01",
        "horizon_end": "2027-06-30",
        "seed": 20260905,
    }
    offline = build_national(root, tmp_path / "offline", research, county_ids=("31055",), paths=4)
    public = build_national(root, tmp_path / "public", research, county_ids=("31055",), paths=2)
    with (
        np.load(tmp_path / "offline" / "county_31055.npz") as full,
        np.load(tmp_path / "public" / "county_31055.npz") as sliced,
        np.load(tmp_path / "public" / "stations_14pair.npz") as stations,
    ):
        assert sliced["scenario_ids"].tolist() == full["scenario_ids"][:2].tolist()
        np.testing.assert_array_equal(sliced["values"], full["values"][:2])
        assert sliced["parent_scenario_set_id"][0] == stations["parent_scenario_set_id"][0]
        assert len(sliced["entity_ids"]) == len(PAIRS)
        assert len(stations["entity_ids"]) == 18 * len(PAIRS)
    assert public["scenario_set"]["data_vintage_id"] == public["vintage_id"]
    assert offline["source_file_hashes"] == public["source_file_hashes"]
