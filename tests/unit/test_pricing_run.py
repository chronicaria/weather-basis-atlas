"""Tests enforcing build-plan Sections 8.2, 8.3, and 8.4 quote production."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from weather_basis.io import sha256, write_npy, write_parquet
from weather_basis.pricing.run import run_quotes


def _inputs(root) -> dict:
    write_npy(np.array(["01001", "01003"]), root / "data/panel/fips.npy")
    write_npy(np.array(["STATION"]), root / "data/panel/station_ids.npy")
    rng = np.random.default_rng(7)
    county_a = rng.normal(100, 15, 80).clip(0)
    county_b = rng.normal(130, 20, 80).clip(0)
    station = 0.6 * county_a + 0.4 * county_b + rng.normal(0, 2, 80)
    write_npy(
        np.vstack((county_a, county_b, station)).astype(np.float32),
        root / "results/draws/R2j_aligned/HDD-01_site.npy",
    )
    write_parquet(
        pd.DataFrame(
            {
                "pair": ["HDD-01", "HDD-01"],
                "fips": ["01001", "01003"],
                "station_pit": ["STATION", "STATION"],
                "h_pit": [0.5, 0.4],
            }
        ),
        root / "results/atlas/pairs.parquet",
    )
    rows = []
    for fips, center in (("01001", 100), ("01003", 130)):
        for season in range(1990, 2026):
            rows.append({"fips": fips, "season": season, "index": center + (season % 11)})
    write_parquet(pd.DataFrame(rows), root / "results/indices/county_HDD-01.parquet")
    return {
        "seed": 9,
        "contracts": {"multiplier_usd": 20},
        "quotes": {
            "z_grid": [-1, 0],
            "percentile_grid": [0.5, 0.95],
            "lambda_B": 16,
            "w": 0.5,
            "alpha": 0.95,
            "friction_ticks": 1,
        },
    }


def test_run_quotes_writes_deterministic_decomposed_grid(tmp_path) -> None:
    """Sections 8.2--8.4: R2j draws yield both payoff grids and a clean gate report."""
    cfg = _inputs(tmp_path)
    first = run_quotes(tmp_path, cfg)
    first_hash = sha256(first.quotes_path)
    second = run_quotes(tmp_path, cfg)
    assert sha256(second.quotes_path) == first_hash
    quotes = pd.read_parquet(first.quotes_path)
    assert len(quotes) == 16
    assert set(quotes["strike_mode"]) == {"standardized", "percentile"}
    assert set(quotes["payoff"]) == {"call", "put"}
    assert (quotes["bid"] <= quotes["mid"]).all()
    assert (quotes["mid"] <= quotes["ask"]).all()
    assert {"residual_load_ask", "residual_load_bid", "model_load", "friction"}.issubset(
        quotes.columns
    )
    coherence = json.loads(first.coherence_path.read_text())
    assert coherence["gate_violations"] == 0
