"""Deterministic quote-table production from the R2j site draws (plan Section 8)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_basis.io import atomic_write_bytes, load_npy, write_parquet
from weather_basis.pricing.coherence import (
    CoherenceReport,
    check_distribution,
    check_quote,
    diagnostics_for_asks,
)
from weather_basis.pricing.distribution import SortedSamples
from weather_basis.pricing.quotes import HedgeSpec, JointDraws, PayoffSpec, loaded_quote
from weather_basis.pricing.strikes import percentile_strikes, standardized_strikes


@dataclass(frozen=True)
class QuoteRunReport:
    """Output locations and counts from one deterministic quote build."""

    n_quotes: int
    n_counties: int
    n_pairs: int
    quotes_path: Path
    coherence_path: Path


def _value(config: Any, group: str, key: str, default: Any) -> Any:
    section = config.get(group, {}) if isinstance(config, dict) else getattr(config, group, {})
    return (
        section.get(key, default)
        if isinstance(section, dict)
        else getattr(section, key, default)
    )


def _seed(config: Any) -> int:
    value = (
        config.get("seed", 20260901)
        if isinstance(config, dict)
        else getattr(config, "seed", 20260901)
    )
    return int(value)


def _burn(index_table: pd.DataFrame, fips: str, window: int = 30) -> np.ndarray:
    rows = index_table.loc[index_table["fips"].astype(str).str.zfill(5) == fips]
    values = rows.sort_values("season", kind="mergesort")["index"].to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if not values.size:
        raise ValueError(f"no finite burn observations for county {fips}")
    return values[-window:]


def _model_load(
    burn: np.ndarray,
    payoff: PayoffSpec,
    *,
    B: int,
    seed: np.random.SeedSequence,
) -> float:
    """Section 8.3's B year-bootstrap standard deviation of burn mean payoff."""
    if B < 2:
        raise ValueError("quotes.lambda_B must be at least two")
    rng = np.random.default_rng(seed)
    n = burn.size
    sampled = burn[rng.integers(0, n, size=(B, n))]
    if payoff.kind == "call":
        payouts = payoff.multiplier * np.maximum(sampled - payoff.strike, 0.0)
    else:
        payouts = payoff.multiplier * np.maximum(payoff.strike - sampled, 0.0)
    return float(np.std(payouts.mean(axis=1), ddof=1))


def _draws_for_pair(root: Path, pair: str, n_series: int) -> np.ndarray:
    path = root / "results/draws/R2j_aligned" / f"{pair}_site.npy"
    if not path.exists():
        raise FileNotFoundError(f"missing aligned R2j site draws: {path}")
    draws = load_npy(path)
    if draws.ndim != 2 or draws.shape[0] != n_series or draws.shape[1] == 0:
        raise ValueError(f"{path} must have shape ({n_series}, M) with M > 0")
    return draws


def run_quotes(root: Path, cfg: Any) -> QuoteRunReport:
    """Build all standardized/percentile call and put quote indications.

    Axis zero of every aligned draw array follows ``fips.npy`` then
    ``station_ids.npy``.  That convention is also used by the simulator, so
    this function never joins paths by simulation value or relies on an
    incidental DataFrame ordering.
    """
    root = Path(root)
    fips = np.asarray(load_npy(root / "data/panel/fips.npy"), dtype=str)
    station_ids = np.asarray(load_npy(root / "data/panel/station_ids.npy"), dtype=str)
    n_counties, n_stations = fips.size, station_ids.size
    if n_counties == 0:
        raise ValueError("fips.npy must not be empty")
    atlas_path = root / "results/atlas/pairs.parquet"
    if not atlas_path.exists():
        raise FileNotFoundError(f"missing atlas pairs table: {atlas_path}")
    atlas = pd.read_parquet(atlas_path)
    required_atlas = {"pair", "fips", "station_pit", "h_pit"}
    if missing := required_atlas.difference(atlas.columns):
        raise ValueError(f"atlas pairs table missing columns: {sorted(missing)}")
    pairs = tuple(sorted(atlas["pair"].dropna().astype(str).unique()))
    if not pairs:
        raise ValueError("atlas pairs table contains no pairs")
    multiplier = float(_value(cfg, "contracts", "multiplier_usd", 20.0))
    z_grid = np.asarray(_value(cfg, "quotes", "z_grid", (-1.5, -1, -0.5, 0, 0.5, 1, 1.5)))
    percentile_grid = np.asarray(_value(cfg, "quotes", "percentile_grid", (0.5, 0.8, 0.95)))
    bootstrap_B = int(_value(cfg, "quotes", "lambda_B", 200))
    records: list[dict[str, Any]] = []
    report = CoherenceReport()
    ask_increasing = ask_nonconvex = 0
    station_positions = {station: n_counties + i for i, station in enumerate(station_ids)}
    county_positions = {code: i for i, code in enumerate(fips)}
    for pair_index, pair in enumerate(pairs):
        index_path = root / "results/indices" / f"county_{pair}.parquet"
        if not index_path.exists():
            raise FileNotFoundError(f"missing county index table: {index_path}")
        index_table = pd.read_parquet(index_path)
        if not {"fips", "season", "index"}.issubset(index_table.columns):
            raise ValueError(f"county index table has invalid columns: {index_path}")
        draws = _draws_for_pair(root, pair, n_counties + n_stations)
        pair_atlas = atlas.loc[atlas["pair"].astype(str) == pair].copy()
        pair_atlas["_fips"] = pair_atlas["fips"].astype(str).str.zfill(5)
        by_fips = pair_atlas.drop_duplicates("_fips", keep="last").set_index("_fips")
        missing_atlas = sorted(set(fips).difference(by_fips.index))
        if missing_atlas:
            raise ValueError(f"atlas is missing {len(missing_atlas)} counties for {pair}")
        for county_index, county_fips in enumerate(fips):
            burn = _burn(index_table, county_fips)
            grids = (
                standardized_strikes(burn, z_grid),
                percentile_strikes(burn, percentile_grid),
            )
            county_samples = SortedSamples(draws[county_positions[county_fips]])
            coherence_grid = np.linspace(0.0, county_samples.quantiles(np.array([0.999]))[0], 41)
            report.merge(check_distribution(county_samples, coherence_grid, multiplier))
            atlas_row = by_fips.loc[county_fips]
            station = str(atlas_row["station_pit"])
            position = station_positions.get(station)
            station_draws = None if position is None else draws[position]
            station_model = (
                "available"
                if station_draws is not None and np.isfinite(station_draws).all()
                else "unavailable"
            )
            joint = JointDraws(
                draws[county_index], station_draws if station_model == "available" else None
            )
            hedge = HedgeSpec(
                station=station,
                station_model=station_model,
                atlas_h=float(atlas_row["h_pit"]) if pd.notna(atlas_row["h_pit"]) else None,
            )
            for grid in grids:
                asks: list[float] = []
                for strike_index, strike in enumerate(grid.strikes):
                    for payoff_index, payoff_kind in enumerate(("call", "put")):
                        payoff = PayoffSpec(float(strike), payoff_kind, multiplier)
                        load_seed = np.random.SeedSequence(
                            [_seed(cfg), pair_index, county_index, strike_index, payoff_index]
                        )
                        quote = loaded_quote(
                            payoff,
                            joint,
                            hedge,
                            cfg,
                            _model_load(burn, payoff, B=bootstrap_B, seed=load_seed),
                        )
                        report.merge(check_quote(quote))
                        asks.append(quote.ask)
                        row = asdict(quote)
                        row.update(
                            {
                                "pair": pair,
                                "fips": county_fips,
                                "payoff": payoff_kind,
                                "strike_mode": grid.mode,
                                "strike": int(strike),
                                "grid_value": float(
                                    z_grid[strike_index]
                                    if grid.mode == "standardized"
                                    else percentile_grid[strike_index]
                                ),
                                "index_rarely_positive": grid.index_rarely_positive,
                                "digital": float(county_samples.digital(np.array([strike]))[0]),
                            }
                        )
                        records.append(row)
                # Ask shape is useful but intentionally non-gating.  Calls and
                # puts each have their own shape series, not an interleaving.
                for payoff_offset in (0, 1):
                    shape = diagnostics_for_asks(grid.strikes, np.asarray(asks[payoff_offset::2]))
                    ask_increasing += shape["ask_increasing"]
                    ask_nonconvex += shape["ask_nonconvex"]
    quotes = pd.DataFrame.from_records(records)
    output = root / "results/quotes/quotes.parquet"
    coherence_output = root / "results/quotes/coherence.json"
    write_parquet(quotes, output)
    payload = {
        "diagnostics": {
            "ask_increasing": ask_increasing,
            "ask_nonconvex": ask_nonconvex,
            "n_quotes": len(quotes),
        },
        "gate_violations": int(sum(report.violations.values())),
        "violations": dict(sorted(report.violations.items())),
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    atomic_write_bytes(coherence_output, data.encode())
    if not report.ok:
        raise RuntimeError(f"quote coherence failed: {payload['violations']}")
    return QuoteRunReport(len(quotes), n_counties, len(pairs), output, coherence_output)
