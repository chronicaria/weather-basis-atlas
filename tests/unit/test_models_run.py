"""Plan Sections 7.1, 7.4, and 7.6 orchestration smoke tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from weather_basis.config import load_config
from weather_basis.models.run import run_site_simulation, run_tournament


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
