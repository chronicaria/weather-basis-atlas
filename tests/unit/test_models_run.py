"""Plan Sections 7.1, 7.4, and 7.6 orchestration smoke tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.config import load_config
from weather_basis.contracts.calendar import PAIRS
from weather_basis.models.run import (
    _index_comparator_draws,
    _joint_daily_draws,
    _joint_diagnostic_summary,
    _pair_history,
    _score_frame,
    run_site_simulation,
    run_tournament,
)
from weather_basis.models.run_daily import _load_or_build_blocks, _subset_blocks


def _fixture_root(tmp_path: Path) -> Path:
    panel = tmp_path / "data" / "panel"
    panel.mkdir(parents=True)
    dates = np.arange("1951-01-01", "2026-07-01", dtype="datetime64[D]")
    rng = np.random.default_rng(9)
    temperature = (
        55
        + 20 * np.sin(np.arange(dates.size) * 2 * np.pi / 365)[:, None]
        + rng.normal(0, 2, (dates.size, 2))
    ).astype("float32")
    np.save(panel / "tavg_f32.npy", temperature)
    np.save(panel / "dates.npy", dates)
    np.save(panel / "fips.npy", np.array(["01001", "01003"]))
    return tmp_path


def test_tournament_writes_scores_selection_and_manifest(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    cfg = load_config(
        Path("config/defaults.yaml"),
        {"simulate": {"M_tournament": 12}, "tournament": {"origins": [1991, 1991], "B": 8}},
    )
    result = run_tournament(root, cfg)
    assert result["selection"].is_file()
    assert (root / "results" / "tournament" / "scores" / "HDD-01.parquet").is_file()
    assert (root / "results" / "manifests" / "tournament.json").is_file()
    selection = pd.read_parquet(result["selection"])
    assert "n_counties" in selection
    diagnostics = pd.read_parquet(root / "results/tournament/calibration_by_origin.parquet")
    assert {
        "skewness",
        "excess_kurtosis",
        "ljung_box_q10",
        "mean_z2",
        "variance_regime_ratio",
        "diagnostic_basis",
    }.issubset(diagnostics.columns)
    assert diagnostics["diagnostic_basis"].eq("daily_R2_standardized_innovation").all()
    assert (root / "results/tournament/determinism.json").is_file()
    parameters = pd.read_parquet(root / "results/models/params/tournament_metadata.parquet")
    assert {"z_sha256", "z_start", "z_end", "mean_path", "ar_path"}.issubset(parameters)
    assert parameters["daily_model"].eq("R2").all()


def test_site_simulation_writes_sorted_and_aligned_draws(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    cfg = load_config(Path("config/defaults.yaml"), {"simulate": {"M_site": 12}})
    result = run_site_simulation(root, cfg)
    sorted_draws = np.load(result["draws"] / "HDD-01_site.npy")
    aligned = np.load(result["aligned"] / "HDD-01_site.npy")
    assert sorted_draws.shape == aligned.shape == (2, 12)
    rerun = run_site_simulation(root, cfg)
    assert np.array_equal(aligned, np.load(rerun["aligned"] / "HDD-01_site.npy"))
    assert np.isfinite(aligned).all()
    assert np.all(sorted_draws[:, 1:] >= sorted_draws[:, :-1])


def test_vectorized_origin_draws_and_scores_are_seed_deterministic(tmp_path: Path) -> None:
    """Plan Sections 7.5--7.6: one seeded origin emits complete county scores."""
    root = _fixture_root(tmp_path)
    cfg = load_config(Path("config/defaults.yaml"), {"simulate": {"M_tournament": 24}})
    values = np.load(root / "data/panel/tavg_f32.npy")
    dates = np.load(root / "data/panel/dates.npy")
    labels = np.load(root / "data/panel/fips.npy")
    seasons, history = _pair_history(values, dates, PAIRS[0])
    origin = 1991
    first = _index_comparator_draws(history, seasons, origin, 24, np.random.SeedSequence(71), cfg)
    second = _index_comparator_draws(history, seasons, origin, 24, np.random.SeedSequence(71), cfg)
    assert all(np.array_equal(first[rung], second[rung]) for rung in ("R0", "R1"))
    frame = _score_frame(
        first,
        history[np.searchsorted(seasons, origin)],
        labels,
        PAIRS[0],
        origin,
    )
    assert len(frame) == 2 * 2
    assert frame["crps"].notna().all()


def test_joint_daily_draws_share_a_seeded_daily_plan(tmp_path: Path) -> None:
    """The rolling R2j primitive is daily and byte-repeatable for a shared seed."""
    root = _fixture_root(tmp_path)
    cfg = load_config(Path("config/defaults.yaml"), {"simulate": {"M_tournament": 13}})
    values = np.load(root / "data/panel/tavg_f32.npy")
    dates = np.load(root / "data/panel/dates.npy")
    blocks = _subset_blocks(_load_or_build_blocks(root, cfg), np.array([0, 1]))
    first, fit = _joint_daily_draws(
        values, dates, blocks, PAIRS[0], 1991, 13, cfg, np.random.SeedSequence(271)
    )
    second, _ = _joint_daily_draws(
        values, dates, blocks, PAIRS[0], 1991, 13, cfg, np.random.SeedSequence(271)
    )
    assert first.shape == (2, 13)
    assert np.array_equal(first, second)
    assert fit.z.shape[1] == 2


def test_joint_diagnostic_uses_registered_pooled_and_exact_sign_criteria() -> None:
    frame = pd.DataFrame(
        {
            "r2j_crps": [0.8] * 20,
            "independent_r2_crps": [1.0] * 20,
            "r2j_beats_independent": [True] * 20,
        }
    )
    summary = _joint_diagnostic_summary(frame)
    assert summary["mean_crps_improves"]
    assert summary["sign_test_passes"]
    assert summary["r2j_wins"] == 20
    assert summary["n_rows"] == 20
