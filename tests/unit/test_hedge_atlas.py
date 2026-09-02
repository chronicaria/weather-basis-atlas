"""Unit coverage for plan Sections 6.4, 6.5, 6.6, and 6.7."""

from __future__ import annotations

import numpy as np
import pandas as pd

from weather_basis.hedge.atlas import PairAtlasInput, run_atlas
from weather_basis.hedge.bootstrap import stability, year_block_bootstrap
from weather_basis.hedge.selection import highest_train_corr, nearest, point_in_time_best
from weather_basis.hedge.zero_distance import station_own_county_table


def test_nearest_uses_geodesic_distance_and_deterministic_ties() -> None:
    counties = np.array([[-87.90, 41.98], [-93.27, 44.98]])
    stations = np.array([[-87.90, 41.98], [-93.27, 44.98]])
    assert nearest(counties, stations).tolist() == [0, 1]
    assert nearest(counties[:1], np.repeat(stations[:1], 2, axis=0)).tolist() == [0]


def test_highest_train_corr_does_not_select_an_all_missing_station_set() -> None:
    corr = np.array([[[0.1, 0.5], [np.nan, np.nan]]])
    assert highest_train_corr(corr).tolist() == [[1, -1]]


def test_point_in_time_best_uses_oos_history_before_current_origin() -> None:
    # Station 0 has stronger training R² but poor realized OOS residuals.  Once
    # five prior OOS observations exist, station 1 must win on trailing OOS HE.
    t_count = 8
    exposure = np.tile(np.arange(t_count, dtype=float)[:, None], (1, 1))
    resid = np.empty((t_count, 1, 2))
    resid[:, 0, 0] = exposure[:, 0] * 2
    resid[:, 0, 1] = 0.01
    r2 = np.zeros_like(resid)
    r2[:, 0, 0] = 0.9
    r2[:, 0, 1] = 0.2
    chosen = point_in_time_best(resid, exposure, r2, np.array([1981, 1981]))
    assert chosen[:5, 0].tolist() == [0] * 5
    assert chosen[5:, 0].tolist() == [1] * 3


def test_point_in_time_best_enforces_registered_first_test_schedule() -> None:
    """Plan Section 6.2: a station cannot be selected before its registered test year."""
    resid = np.zeros((4, 1, 1))
    r2 = np.ones_like(resid)
    selected = point_in_time_best(
        resid,
        np.arange(4.0)[:, None],
        r2,
        np.array([1989]),
        seasons=np.array([1986, 1987, 1988, 1989]),
    )
    assert selected[:, 0].tolist() == [-1, -1, -1, 0]


def test_joint_bootstrap_is_fixed_seed_and_retains_all_station_statistics() -> None:
    exposure = np.arange(12, dtype=float)[:, None]
    pit = exposure * 0.3
    near = exposure * 0.5
    stations = np.stack((pit, near), axis=2)
    first = year_block_bootstrap(
        pit, near, stations, exposure, B=40, seed=np.random.SeedSequence(8)
    )
    second = year_block_bootstrap(
        pit, near, stations, exposure, B=40, seed=np.random.SeedSequence(8)
    )
    assert np.array_equal(first.weights, second.weights)
    assert np.allclose(first.he_pit, second.he_pit, equal_nan=True)
    assert first.he_station.shape == (40, 1, 2)
    assert first.h_pit.shape == (40, 1)
    assert first.h_station.shape == (40, 1, 2)
    low, high = first.interval(first.he_pit)
    assert np.all(low <= high)


def test_stability_is_fraction_of_bootstrap_wins() -> None:
    he = np.array([[[0.8, 0.1]], [[0.2, 0.9]], [[0.4, 0.3]]])
    answer = stability(he, np.array([0]))
    assert np.allclose(answer, [2 / 3])


def test_zero_distance_keeps_not_evaluable_station_pair() -> None:
    residuals = np.array([[[0.0, np.nan]], [[0.0, np.nan]], [[0.0, np.nan]]])
    anomalies = np.array([[1.0], [2.0], [3.0]])
    table = station_own_county_table(
        "HDD-01",
        np.array(["A", "B"]),
        np.array([0, 0]),
        residuals,
        anomalies,
        np.arange(2000, 2003),
    )
    assert table.not_evaluable.tolist() == [False, True]
    assert table.n_test.tolist() == [3, 0]
    assert "worst_season" in table
    assert "fips" in table


def test_atlas_writes_registered_tensors_and_complete_zero_distance_schema(tmp_path) -> None:
    """Plan Sections 6.3, 6.6, and 6.7: derived rolling evidence is persisted."""
    seasons = np.arange(1981, 1987)
    exposure = np.arange(6.0)[:, None]
    residuals = np.stack((exposure * 0.2, exposure * 0.3), axis=2)
    h = np.ones_like(residuals)
    train_r2 = np.full_like(residuals, 0.25)
    selected = point_in_time_best(
        residuals, exposure, train_r2, np.array([1981, 1981]), min_oos=1, seasons=seasons
    )
    rows, columns = np.arange(len(seasons))[:, None], np.array([[0]])
    pit_residual = residuals[rows, columns, np.maximum(selected, 0)]
    pit_h = h[rows, columns, np.maximum(selected, 0)]
    pit_residual[selected < 0] = np.nan
    pit_h[selected < 0] = np.nan
    bootstrap = year_block_bootstrap(
        pit_residual,
        residuals[:, :, 0],
        residuals,
        exposure,
        B=5,
        seed=np.random.SeedSequence(1),
        h_pit=pit_h,
        h_station=h,
    )
    item = PairAtlasInput(
        "HDD-01",
        seasons,
        np.array(["00001"]),
        np.array(["A", "B"]),
        exposure,
        residuals,
        h,
        np.zeros_like(h),
        train_r2,
        np.array([0]),
        selected,
        highest_train_corr(train_r2),
        bootstrap,
    )
    zero = station_own_county_table(
        "HDD-01",
        np.array(["A", "B"]),
        np.array([0, 0]),
        residuals,
        exposure,
        seasons,
        fips=np.array(["00001"]),
    )
    oos = pd.DataFrame(
        {
            "pair": ["HDD-01"],
            "fips": ["00001"],
            "season": [1981],
            "a_c": [0.0],
            "a_j_pit": [0.0],
            "a_j_nearest": [0.0],
            "r_pit": [0.0],
            "r_nearest": [0.0],
        }
    )
    run_atlas([item], out_dir=tmp_path, zero_distance=zero, oos=oos)
    tensor_path = tmp_path / "tensors/HDD-01.npz"
    first_tensor = tensor_path.read_bytes()
    run_atlas([item], out_dir=tmp_path, zero_distance=zero, oos=oos)
    assert tensor_path.read_bytes() == first_tensor
    assert set(np.load(tensor_path).files) == {
        "alpha",
        "h",
        "resid",
        "seasons",
        "train_r2",
    }
    station_columns = set(pd.read_parquet(tmp_path / "stations.parquet").columns)
    assert {"worst_season", "h_mean"} <= station_columns
    zero_columns = set(pd.read_parquet(tmp_path / "zero_distance.parquet").columns)
    assert {"fips", "not_evaluable", "worst_season"} <= zero_columns
    assert pd.read_parquet(tmp_path / "oos.parquet").equals(oos)
