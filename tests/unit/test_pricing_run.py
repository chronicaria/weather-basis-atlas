"""Tests enforcing build-plan Sections 8.2, 8.3, and 8.4 quote production."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from weather_basis.io import sha256, write_npy, write_parquet
from weather_basis.pricing.run import (
    _model_load,
    _site_station_ids,
    check_two_seed_agreement,
    run_quotes,
    verify_quote_rows,
)


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
    assert coherence["diagnostics"]["recompute"]["n_checked"] == 16
    assert coherence["diagnostics"]["recompute"]["max_abs_error"] <= 1e-6
    assert coherence["diagnostics"]["seed_agreement"]["status"] == "not_run"
    assert verify_quote_rows(tmp_path, cfg, n_rows=16)["max_abs_error"] <= 1e-6

    tampered = quotes.copy()
    tampered.loc[tampered.index[0], "ask"] += 0.01
    with pytest.raises(RuntimeError, match="quote recomputation failed"):
        verify_quote_rows(tmp_path, cfg, quotes=tampered, n_rows=16)


def test_year_block_model_load_is_deterministic() -> None:
    burn = np.arange(30, dtype=float)
    payoff = type("Payoff", (), {"kind": "call", "multiplier": 20.0, "strike": 12.0})()
    first = _model_load(burn, payoff, B=32, seed=np.random.SeedSequence(11))
    second = _model_load(burn, payoff, B=32, seed=np.random.SeedSequence(11))
    assert first == second and first > 0


def test_site_station_axis_excludes_diagnostic_only_stations(tmp_path) -> None:
    panel = tmp_path / "data/panel"
    metadata = tmp_path / "data/metadata"
    panel.mkdir(parents=True)
    metadata.mkdir(parents=True)
    write_npy(np.array(["CME_A", "NE_A", "CME_B"]), panel / "station_ids.npy")
    pd.DataFrame(
        {
            "ghcnd_id": ["CME_A", "NE_A", "CME_B"],
            "role": ["cme", "nebraska", "cme"],
        }
    ).to_csv(metadata / "station_registry.csv", index=False)
    assert _site_station_ids(tmp_path).tolist() == ["CME_A", "CME_B"]


def test_two_seed_agreement_checks_mid_and_bootstrapped_ask(tmp_path) -> None:
    cfg = _inputs(tmp_path)
    primary = np.load(tmp_path / "results/draws/R2j_aligned/HDD-01_site.npy")
    # A distinct but close independent draw run exercises the actual
    # two-seed path rather than treating one matrix as both samples.
    alternate = primary.copy()
    alternate[:, ::11] += 0.01
    alternate_dir = tmp_path / "results/draws/R2j_aligned_seed2"
    alternate_dir.mkdir(parents=True)
    np.savez(
        alternate_dir / "HDD-01_site.npz",
        fips=np.array(["01001", "01003"]),
        station_ids=np.array(["STATION"]),
        county=alternate[:2],
        station=alternate[2:],
        seed=np.array([9, 2]),
    )
    result = check_two_seed_agreement(tmp_path, cfg, alternate_dir)
    assert result["status"] == "passed"
    assert result["n_checked"] == 2
    assert result["ask_bootstrap_B"] == 16
    # Quote builds discover the compact model-stage artifact automatically and
    # persist the result alongside the other coherence diagnostics.
    built = run_quotes(tmp_path, cfg)
    diagnostics = json.loads(built.coherence_path.read_text())["diagnostics"]["seed_agreement"]
    assert diagnostics["status"] == "passed" and diagnostics["n_checked"] == 2
