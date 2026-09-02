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
    check_seed_agreement,
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
        section.get(key, default) if isinstance(section, dict) else getattr(section, key, default)
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
    sampled = _year_block_resamples(burn, B=B, seed=seed)
    if payoff.kind == "call":
        payouts = payoff.multiplier * np.maximum(sampled - payoff.strike, 0.0)
    else:
        payouts = payoff.multiplier * np.maximum(payoff.strike - sampled, 0.0)
    return float(np.std(payouts.mean(axis=1), ddof=1))


def _year_block_resamples(burn: np.ndarray, *, B: int, seed: np.random.SeedSequence) -> np.ndarray:
    """Return B bootstrap samples made from calendar-year blocks.

    The burn input has one annual index per observation.  Consequently each
    one-year block is the atomic time block prescribed by Section 8.3; keeping
    this operation separate makes that convention explicit and avoids the
    misleading appearance of an arbitrary IID draw of individual daily data.
    """
    values = np.asarray(burn, dtype=np.float64).reshape(-1)
    if values.size == 0:
        raise ValueError("burn samples must not be empty")
    if B < 2:
        raise ValueError("quotes.lambda_B must be at least two")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, values.size, size=(B, values.size))
    return values[starts]


def _normalise_station(value: Any) -> str:
    """Avoid serialising pandas' NaN sentinel as the fictional station 'nan'."""
    return str(value) if value is not None and pd.notna(value) else "unavailable"


def _quote_context(
    *,
    draws: np.ndarray,
    county_index: int,
    station: str,
    station_positions: dict[str, int],
    atlas_h: float | None,
    payoff: PayoffSpec,
    cfg: Any,
    load_seed: np.random.SeedSequence,
    burn: np.ndarray,
    bootstrap_B: int,
) -> tuple[Any, SortedSamples]:
    """Build one quote from an aligned matrix using the registered fallback."""
    county_draws = np.asarray(draws[county_index])
    position = station_positions.get(station)
    station_draws = None if position is None else np.asarray(draws[position])
    station_model = (
        "available"
        if station_draws is not None and np.isfinite(station_draws).all()
        else "unavailable"
    )
    joint = JointDraws(county_draws, station_draws if station_model == "available" else None)
    hedge = HedgeSpec(station=station, station_model=station_model, atlas_h=atlas_h)
    return (
        loaded_quote(
            payoff,
            joint,
            hedge,
            cfg,
            _model_load(burn, payoff, B=bootstrap_B, seed=load_seed),
        ),
        SortedSamples(county_draws),
    )


def _ask_bootstrap_se(
    payoff: PayoffSpec,
    joint: JointDraws,
    hedge: HedgeSpec,
    cfg: Any,
    model_load: float,
    *,
    B: int,
    seed: np.random.SeedSequence,
) -> float:
    """Bootstrap the loaded ask over aligned simulation paths (Section 8.4)."""
    county = np.asarray(joint.county, dtype=np.float64).reshape(-1)
    if county.size < 2 or B < 2:
        return 0.0
    station = (
        None if joint.station is None else np.asarray(joint.station, dtype=np.float64).reshape(-1)
    )
    rng = np.random.default_rng(seed)
    asks = np.empty(B, dtype=np.float64)
    # Process one bootstrap replicate at a time: M=10,000 uses bounded memory
    # and preserves county/station path alignment under resampling.
    for replicate in range(B):
        positions = rng.integers(0, county.size, size=county.size)
        resampled = JointDraws(county[positions], None if station is None else station[positions])
        asks[replicate] = loaded_quote(payoff, resampled, hedge, cfg, model_load).ask
    return float(np.std(asks, ddof=1))


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
            station = _normalise_station(atlas_row["station_pit"])
            atlas_h = float(atlas_row["h_pit"]) if pd.notna(atlas_row["h_pit"]) else None
            for grid in grids:
                asks: list[float] = []
                for strike_index, strike in enumerate(grid.strikes):
                    for payoff_index, payoff_kind in enumerate(("call", "put")):
                        payoff = PayoffSpec(float(strike), payoff_kind, multiplier)
                        load_seed = np.random.SeedSequence(
                            [_seed(cfg), pair_index, county_index, strike_index, payoff_index]
                        )
                        quote, county_samples = _quote_context(
                            draws=draws,
                            county_index=county_index,
                            station=station,
                            station_positions=station_positions,
                            atlas_h=atlas_h,
                            payoff=payoff,
                            cfg=cfg,
                            load_seed=load_seed,
                            burn=burn,
                            bootstrap_B=bootstrap_B,
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
    recompute = verify_quote_rows(root, cfg, quotes=quotes, n_rows=50)
    seed_agreement = _optional_seed_agreement(root, cfg)
    output = root / "results/quotes/quotes.parquet"
    coherence_output = root / "results/quotes/coherence.json"
    write_parquet(quotes, output)
    payload = {
        "diagnostics": {
            "ask_increasing": ask_increasing,
            "ask_nonconvex": ask_nonconvex,
            "n_quotes": len(quotes),
            "recompute": recompute,
            "seed_agreement": seed_agreement,
        },
        "gate_violations": int(sum(report.violations.values())),
        "violations": dict(sorted(report.violations.items())),
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    atomic_write_bytes(coherence_output, data.encode())
    if not report.ok:
        raise RuntimeError(f"quote coherence failed: {payload['violations']}")
    return QuoteRunReport(len(quotes), n_counties, len(pairs), output, coherence_output)


def _record_grid_index(row: pd.Series, z_grid: np.ndarray, percentile_grid: np.ndarray) -> int:
    values = z_grid if str(row["strike_mode"]) == "standardized" else percentile_grid
    matches = np.flatnonzero(np.isclose(values.astype(float), float(row["grid_value"])))
    if matches.size != 1:
        raise ValueError(f"cannot recover registered grid position for quote row {row.name}")
    return int(matches[0])


def verify_quote_rows(
    root: Path,
    cfg: Any,
    *,
    quotes: pd.DataFrame | None = None,
    n_rows: int = 50,
    tolerance: float = 1e-6,
) -> dict[str, float | int]:
    """Recompute a fixed random sample of stored quotes directly from R2j paths.

    This is the authoritative Phase-6 quote check: it independently recreates
    the payoff, hedge/load decomposition, and quote-table row, rather than
    merely checking a precomputed ordering inequality.
    """
    root = Path(root)
    table = (
        quotes if quotes is not None else pd.read_parquet(root / "results/quotes/quotes.parquet")
    )
    if table.empty:
        raise ValueError("cannot verify an empty quote table")
    required = {"pair", "fips", "payoff", "strike_mode", "strike", "grid_value", "station", "h"}
    if missing := required.difference(table.columns):
        raise ValueError(f"quote table missing recomputation columns: {sorted(missing)}")
    fips = np.asarray(load_npy(root / "data/panel/fips.npy"), dtype=str)
    station_ids = np.asarray(load_npy(root / "data/panel/station_ids.npy"), dtype=str)
    county_positions = {code: i for i, code in enumerate(fips)}
    station_positions = {station: fips.size + i for i, station in enumerate(station_ids)}
    z_grid = np.asarray(_value(cfg, "quotes", "z_grid", (-1.5, -1, -0.5, 0, 0.5, 1, 1.5)))
    percentile_grid = np.asarray(_value(cfg, "quotes", "percentile_grid", (0.5, 0.8, 0.95)))
    bootstrap_B = int(_value(cfg, "quotes", "lambda_B", 200))
    pairs = tuple(sorted(table["pair"].dropna().astype(str).unique()))
    pair_positions = {pair: index for index, pair in enumerate(pairs)}
    rng = np.random.default_rng(_seed(cfg))
    count = min(int(n_rows), len(table))
    selected = table.iloc[np.sort(rng.choice(len(table), size=count, replace=False))]
    index_tables: dict[str, pd.DataFrame] = {}
    draws_cache: dict[str, np.ndarray] = {}
    max_error = 0.0
    fields = (
        "mid",
        "ask",
        "bid_raw",
        "bid",
        "expected_payout",
        "residual_load_ask",
        "residual_load_bid",
        "model_load",
        "friction",
        "h",
    )
    for _, row in selected.iterrows():
        pair = str(row["pair"])
        fips_code = str(row["fips"]).split(".")[0].zfill(5)
        if pair not in draws_cache:
            draws_cache[pair] = _draws_for_pair(root, pair, fips.size + station_ids.size)
            index_tables[pair] = pd.read_parquet(
                root / "results/indices" / f"county_{pair}.parquet"
            )
        grid_index = _record_grid_index(row, z_grid, percentile_grid)
        payoff_index = 0 if str(row["payoff"]) == "call" else 1
        quote, samples = _quote_context(
            draws=draws_cache[pair],
            county_index=county_positions[fips_code],
            station=_normalise_station(row["station"]),
            station_positions=station_positions,
            atlas_h=float(row["h"]) if pd.notna(row["h"]) else None,
            payoff=PayoffSpec(
                float(row["strike"]),
                str(row["payoff"]),
                float(_value(cfg, "contracts", "multiplier_usd", 20.0)),
            ),
            cfg=cfg,
            load_seed=np.random.SeedSequence(
                [
                    _seed(cfg),
                    pair_positions[pair],
                    county_positions[fips_code],
                    grid_index,
                    payoff_index,
                ]
            ),
            burn=_burn(index_tables[pair], fips_code),
            bootstrap_B=bootstrap_B,
        )
        # Digital is part of the row contract too, though it is derived from
        # the county marginal rather than the loaded hedge quote.
        expected = asdict(quote)
        expected["digital"] = float(samples.digital(np.array([row["strike"]]))[0])
        for field in (*fields, "digital"):
            error = abs(float(expected[field]) - float(row[field]))
            max_error = max(max_error, error)
            if error > tolerance:
                raise RuntimeError(
                    f"quote recomputation failed for {pair}/{fips_code} {field}: "
                    f"{error} > {tolerance}"
                )
        if bool(quote.no_bid) != bool(row["no_bid"]) or str(quote.station_model) != str(
            row["station_model"]
        ):
            raise RuntimeError(f"quote recomputation metadata failed for {pair}/{fips_code}")
    return {"n_checked": count, "tolerance": tolerance, "max_abs_error": max_error}


def _optional_seed_agreement(root: Path, cfg: Any) -> dict[str, Any]:
    """Run the registered two-seed check when an independent R2j run is present.

    The pricing package never simulates paths (by its import boundary), so the
    model stage supplies the second run as compact labelled county/station
    panels in this sibling directory.  Keeping an explicit ``not_run`` result
    prevents a release from mistaking absence of the input for a passing Monte
    Carlo comparison.
    """
    alternate = root / "results/draws/R2j_aligned_seed2"
    if not alternate.is_dir():
        return {"status": "not_run", "reason": f"missing {alternate.relative_to(root)}"}
    result = check_two_seed_agreement(root, cfg, alternate)
    if not result["ok"]:
        raise RuntimeError(f"quote seed agreement failed: {result['violations']}")
    return result


def check_two_seed_agreement(root: Path, cfg: Any, alternate_dir: Path) -> dict[str, Any]:
    """Apply the prescribed two-seed mid/ask agreement to 50 fixed rows.

    The model-stage interface is ``{PAIR}_site.npz`` with labelled ``fips``
    (the fixed 50-county panel), all CME ``station_ids``, and aligned
    ``county``/``station`` draw matrices.  At each county/pair it evaluates
    the z=0 standardized call; this makes the comparison stable, auditable,
    and independent of the model's own forecast moments.  Ask standard errors
    use B loaded-payoff bootstrap replicates with county/station paths
    resampled jointly.
    """
    root, alternate_dir = Path(root), Path(alternate_dir)
    fips = np.asarray(load_npy(root / "data/panel/fips.npy"), dtype=str)
    station_ids = np.asarray(load_npy(root / "data/panel/station_ids.npy"), dtype=str)
    atlas = pd.read_parquet(root / "results/atlas/pairs.parquet")
    pairs = tuple(sorted(atlas["pair"].dropna().astype(str).unique()))
    county_positions = {code: i for i, code in enumerate(fips)}
    station_positions = {station: fips.size + i for i, station in enumerate(station_ids)}
    z_grid = np.asarray(_value(cfg, "quotes", "z_grid", (-1.5, -1, -0.5, 0, 0.5, 1, 1.5)))
    z_index = int(np.argmin(np.abs(z_grid.astype(float))))
    bootstrap_B = int(_value(cfg, "quotes", "lambda_B", 200))
    panel_size = int(_value(cfg, "quotes", "seed_panel_counties", 50))
    panel_ranks = np.linspace(0, len(fips) - 1, min(panel_size, len(fips)), dtype=int)
    panel_fips = tuple(fips[panel_ranks])
    report = CoherenceReport()
    max_mid_se = max_ask_se = 0.0
    for pair_index, pair in enumerate(pairs):
        primary = _draws_for_pair(root, pair, fips.size + station_ids.size)
        secondary_path = alternate_dir / f"{pair}_site.npz"
        if not secondary_path.exists():
            raise FileNotFoundError(f"missing independent aligned R2j draws: {secondary_path}")
        secondary_fips, secondary_stations, secondary_county, secondary_station = _seed2_panel(
            secondary_path
        )
        if tuple(secondary_fips) != panel_fips:
            raise ValueError(
                f"independent county labels do not match fixed panel: {secondary_path}"
            )
        if secondary_county.shape != (len(panel_fips), primary.shape[1]):
            raise ValueError(f"independent county draws have wrong shape: {secondary_path}")
        if secondary_station.shape[1] != primary.shape[1]:
            raise ValueError(f"independent station draws have wrong shape: {secondary_path}")
        secondary_county_positions = {code: index for index, code in enumerate(secondary_fips)}
        secondary_station_positions = {
            station: index for index, station in enumerate(secondary_stations)
        }
        secondary_combined = np.vstack((secondary_county, secondary_station))
        secondary_combined_positions = {
            station: len(panel_fips) + position
            for station, position in secondary_station_positions.items()
        }
        pair_atlas = atlas.loc[atlas["pair"].astype(str) == pair].copy()
        pair_atlas["_fips"] = pair_atlas["fips"].astype(str).str.zfill(5)
        atlas_lookup = pair_atlas.drop_duplicates("_fips", keep="last").set_index("_fips")
        index_table = pd.read_parquet(root / "results/indices" / f"county_{pair}.parquet")
        for county_panel_index, code in enumerate(panel_fips):
            row = atlas_lookup.loc[code]
            station = _normalise_station(row["station_pit"])
            atlas_h = float(row["h_pit"]) if pd.notna(row["h_pit"]) else None
            burn = _burn(index_table, code)
            strike = int(standardized_strikes(burn, z_grid).strikes[z_index])
            payoff = PayoffSpec(
                float(strike), "call", float(_value(cfg, "contracts", "multiplier_usd", 20.0))
            )
            load_seed = np.random.SeedSequence(
                [_seed(cfg), pair_index, county_positions[code], z_index, 0]
            )
            primary_quote, primary_samples = _quote_context(
                draws=primary,
                county_index=county_positions[code],
                station=station,
                station_positions=station_positions,
                atlas_h=atlas_h,
                payoff=payoff,
                cfg=cfg,
                load_seed=load_seed,
                burn=burn,
                bootstrap_B=bootstrap_B,
            )
            secondary_quote, secondary_samples = _quote_context(
                draws=secondary_combined,
                county_index=secondary_county_positions[code],
                station=station,
                station_positions=secondary_combined_positions,
                atlas_h=atlas_h,
                payoff=payoff,
                cfg=cfg,
                load_seed=load_seed,
                burn=burn,
                bootstrap_B=bootstrap_B,
            )
            primary_position = station_positions.get(station)
            secondary_position = secondary_station_positions.get(station)
            primary_joint = JointDraws(
                primary[county_positions[code]],
                None if primary_position is None else primary[primary_position],
            )
            secondary_joint = JointDraws(
                secondary_county[secondary_county_positions[code]],
                None if secondary_position is None else secondary_station[secondary_position],
            )
            hedge = HedgeSpec(station, primary_quote.station_model, atlas_h)
            load = primary_quote.model_load
            ask_se_primary = _ask_bootstrap_se(
                payoff,
                primary_joint,
                hedge,
                cfg,
                load,
                B=bootstrap_B,
                seed=np.random.SeedSequence([_seed(cfg), pair_index, county_panel_index, 0, 1]),
            )
            ask_se_secondary = _ask_bootstrap_se(
                payoff,
                secondary_joint,
                hedge,
                cfg,
                load,
                B=bootstrap_B,
                seed=np.random.SeedSequence([_seed(cfg), pair_index, county_panel_index, 1, 1]),
            )
            mid_se_primary = float(
                primary_samples.se_call(np.array([strike]), payoff.multiplier)[0]
            )
            mid_se_secondary = float(
                secondary_samples.se_call(np.array([strike]), payoff.multiplier)[0]
            )
            max_mid_se, max_ask_se = (
                max(max_mid_se, mid_se_primary, mid_se_secondary),
                max(max_ask_se, ask_se_primary, ask_se_secondary),
            )
            report.merge(
                check_seed_agreement(
                    np.array([primary_quote.mid]),
                    np.array([secondary_quote.mid]),
                    np.array([mid_se_primary]),
                    np.array([mid_se_secondary]),
                    sigma=float(_value(cfg, "quotes", "seed_agreement_sigma", 4)),
                    ask_a=np.array([primary_quote.ask]),
                    ask_b=np.array([secondary_quote.ask]),
                    ask_se_a=np.array([ask_se_primary]),
                    ask_se_b=np.array([ask_se_secondary]),
                )
            )
    return {
        "status": "passed" if report.ok else "failed",
        "ok": report.ok,
        "n_checked": len(panel_fips) * len(pairs),
        "panel_rule": "50_evenly_spaced_fips_each_pair_z0_call",
        "ask_bootstrap_B": bootstrap_B,
        "max_mid_se": max_mid_se,
        "max_ask_se": max_ask_se,
        "violations": dict(sorted(report.violations.items())),
    }


def _seed2_panel(path: Path) -> tuple[tuple[str, ...], tuple[str, ...], np.ndarray, np.ndarray]:
    """Read and validate the compact labelled model-stage second-seed panel."""
    with np.load(path, allow_pickle=False) as archive:
        required = {"fips", "station_ids", "county", "station"}
        if missing := required.difference(archive.files):
            raise ValueError(f"independent draw panel missing {sorted(missing)}: {path}")
        fips = tuple(np.asarray(archive["fips"], dtype=str))
        station_ids = tuple(np.asarray(archive["station_ids"], dtype=str))
        county = np.asarray(archive["county"])
        station = np.asarray(archive["station"])
    if county.ndim != 2 or station.ndim != 2 or county.shape[0] != len(fips):
        raise ValueError(f"invalid independent county draw panel: {path}")
    if (
        station.shape[0] != len(station_ids)
        or not np.isfinite(county).all()
        or not np.isfinite(station).all()
    ):
        raise ValueError(f"invalid independent station draw panel: {path}")
    return fips, station_ids, county, station
