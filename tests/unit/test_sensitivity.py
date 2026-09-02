"""Plan Section 7.7: registered 18-county daily-model sensitivity table."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.config import load_config
from weather_basis.contracts.calendar import PAIRS
from weather_basis.indices.anomalies import anomaly
from weather_basis.models.sensitivity import run_sensitivities, sensitivity_specs
from weather_basis.validation.atlas_sensitivity import run_atlas_anomaly_sensitivity


def _root(tmp_path: Path) -> Path:
    panel = tmp_path / "data" / "panel"
    panel.mkdir(parents=True)
    dates = np.arange("1951-01-01", "2026-07-01", dtype="datetime64[D]")
    rng = np.random.default_rng(7)
    values = (
        55
        + 18 * np.sin(np.arange(len(dates))[:, None] * 2 * np.pi / 365.2425)
        + rng.normal(0, 1, (len(dates), 18))
    ).astype("float32")
    fips = np.asarray([f"{1001 + column:05d}" for column in range(18)])
    np.save(panel / "tavg_f32.npy", values)
    np.save(panel / "dates.npy", dates)
    np.save(panel / "fips.npy", fips)
    metadata = tmp_path / "data" / "metadata"
    contracts = tmp_path / "data" / "contracts"
    metadata.mkdir(parents=True)
    contracts.mkdir(parents=True)
    ids = [f"TEST{column:06d}" for column in range(18)]
    pd.DataFrame({"ghcnd_id": ids}).to_csv(metadata / "station_registry.csv", index=False)
    pd.DataFrame({"ghcnd_id": ids, "county_fips": fips}).to_csv(
        contracts / "station_county.csv", index=False
    )
    indices = tmp_path / "results" / "indices"
    indices.mkdir(parents=True)
    seasons = np.arange(1951, 2026)
    annual = rng.normal(250, 25, (len(seasons), 18))
    for pair in PAIRS:
        county = pd.DataFrame(
            {
                "pair": pair.key,
                "fips": np.tile(fips, len(seasons)),
                "season": np.repeat(seasons, len(fips)),
                "index": annual.ravel(),
                "anomaly": anomaly(annual, window=30, min_prior=15).ravel(),
            }
        )
        station_values = annual + rng.normal(0, 5, annual.shape)
        station = pd.DataFrame(
            {
                "pair": pair.key,
                "ghcnd_id": np.tile(ids, len(seasons)),
                "season": np.repeat(seasons, len(ids)),
                "index": station_values.ravel(),
                "anomaly": anomaly(station_values, window=30, min_prior=10).ravel(),
            }
        )
        county.to_parquet(indices / f"county_{pair.key}.parquet", index=False)
        station.to_parquet(indices / f"station_{pair.key}.parquet", index=False)
    return tmp_path


def test_registered_sensitivity_grid_and_output_schema(tmp_path: Path) -> None:
    """Section 7.7: all four one-at-a-time grids render methodology metrics."""
    specs = sensitivity_specs()
    assert len(specs) == 12
    assert {(item.dimension, item.value) for item in specs} >= {
        ("mean_window_years", 30),
        ("mean_window_years", 40),
        ("mean_window_years", -1),
        ("mean_harmonics", 1),
        ("mean_harmonics", 3),
        ("mean_block_days", 5),
        ("mean_block_days", 10),
        ("residual_window_years", 20),
        ("residual_window_years", 40),
    }
    root = _root(tmp_path)
    cfg = load_config(Path("config/defaults.yaml"), {"simulate": {"M_site": 4}})
    output = run_sensitivities(root, cfg)
    frame = pd.read_parquet(output)
    assert len(frame) == 12 * 14 * 18
    assert {
        "dimension",
        "value",
        "mean_index",
        "sd_index",
        "mean_shift_vs_baseline",
        "sd_ratio_vs_baseline",
    }.issubset(frame)
    baseline = frame[(frame.dimension == "mean_window_years") & (frame.value == 40)]
    assert np.allclose(baseline["mean_shift_vs_baseline"], 0)
    assert np.isfinite(frame.loc[frame.dimension != "atlas_anomaly_method", "mean_index"]).all()
    atlas = pd.read_parquet(run_atlas_anomaly_sensitivity(root))
    assert set(atlas.variant_label) == {"trailing_normal", "trend_anomaly"}
    assert atlas["baseline_label"].str.contains("trailing").all()
    assert np.isfinite(atlas["metric_value"]).all()
