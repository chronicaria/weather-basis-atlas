"""Fixture-scale orchestration test for plan sections 7.2--7.4."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from weather_basis.config import load_config
from weather_basis.models.run_daily import build_mean_blocks, run_site_daily


def _daily_fixture(root: Path) -> None:
    directory = root / "data" / "panel"
    directory.mkdir(parents=True)
    dates = np.arange("1980-01-01", "2026-07-01", dtype="datetime64[D]")
    rng = np.random.default_rng(2)
    phase = np.arange(len(dates)) * 2 * np.pi / 365.2425
    values = np.column_stack(
        (
            55 + 15 * np.sin(phase) + rng.normal(0, 2, len(dates)),
            57 + 13 * np.sin(phase + 0.2) + rng.normal(0, 2, len(dates)),
        )
    ).astype("float32")
    np.save(directory / "tavg_f32.npy", values)
    np.save(directory / "dates.npy", dates)
    np.save(directory / "fips.npy", np.array(["01001", "01003"]))


def test_site_daily_writes_chunked_aligned_joint_draws_deterministically(tmp_path: Path) -> None:
    """Sections 7.2--7.4: R2j site run uses fixed blocks and aligned draws."""

    _daily_fixture(tmp_path)
    cfg = load_config(
        Path("config/defaults.yaml"),
        {"simulate": {"M_site": 13, "chunk_series": 1, "window_days": 45}},
    )
    blocks = build_mean_blocks(tmp_path, cfg)
    assert blocks.gram.shape[1:] == (2, 8, 8)
    assert (tmp_path / "data" / "panel" / "mean_blocks.npz").is_file()
    result = run_site_daily(tmp_path, cfg)
    aligned_path = result["aligned"] / "HDD-01_site.npy"
    first = np.load(aligned_path)
    sorted_draws = np.load(result["draws"] / "HDD-01_site.npy")
    assert first.shape == sorted_draws.shape == (2, 13)
    assert np.all(np.isfinite(first))
    assert np.all(sorted_draws[:, 1:] >= sorted_draws[:, :-1])
    seed_panel = np.load(
        tmp_path / "results/draws/R2j_aligned_seed2/HDD-01_site.npz",
        allow_pickle=False,
    )
    assert seed_panel["county"].shape == (50, 13)
    assert seed_panel["station"].shape == (0, 13)
    assert seed_panel["station_ids"].dtype.kind == "U"
    assert seed_panel["fips"].shape == (50,)
    run_site_daily(tmp_path, cfg)
    assert np.array_equal(first, np.load(aligned_path))
