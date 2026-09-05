"""Vectorized payoff and payoff-specific hedge calculations."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from weather_basis.pricing.bootstrap import mean_se
from weather_basis.pricing.v2 import V2Payoff, payoff
from weather_basis.provenance.ids import canonical_json, content_id, file_sha256


def _paths(values: np.ndarray, *, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64).reshape(-1)
    if not result.size or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a non-empty finite path vector")
    return result


def payoff_batch(values: np.ndarray, specs: tuple[V2Payoff, ...]) -> np.ndarray:
    """Return (payoffs, paths), preserving common path order."""
    if not specs:
        raise ValueError("at least one payoff specification is required")
    paths = _paths(values, name="values")
    return np.stack([payoff(paths, spec) for spec in specs])


def hedge_ratios(
    county: np.ndarray, station: np.ndarray, specs: tuple[V2Payoff, ...]
) -> np.ndarray:
    """Recompute one payoff-specific covariance hedge ratio per ticket."""
    tickets = payoff_batch(county, specs)
    station_paths = _paths(station, name="station")
    if station_paths.shape != tickets.shape[1:]:
        raise ValueError("county and station paths must have identical coordinates")
    hedge = station_paths - station_paths.mean()
    var = hedge @ hedge
    if var <= max(np.finfo(float).eps, 1e-12 * max(float(station_paths @ station_paths), 1.0)):
        return np.full(len(specs), np.nan)
    return (tickets - tickets.mean(axis=1, keepdims=True)) @ hedge / var


def batch_quote_metrics(
    county: np.ndarray,
    station: np.ndarray | None,
    burn: np.ndarray,
    specs: tuple[V2Payoff, ...],
    bootstrap_counts: np.ndarray,
) -> dict[str, np.ndarray]:
    """Calculate bounded, reusable quote inputs for compatible tickets.

    ``bootstrap_counts`` is built once per county burn history.  This routine
    never constructs a bootstrap-by-path cube: it holds ticket-by-path
    payoffs and bootstrap-by-ticket means only.
    """
    county_paths = _paths(county, name="county")
    burn_paths = _paths(burn, name="burn")
    county_payoffs = payoff_batch(county_paths, specs)
    burn_payoffs = payoff_batch(burn_paths, specs)
    metrics = {
        "expected_payout": county_payoffs.mean(axis=1),
        "expected_payout_se": county_payoffs.std(axis=1, ddof=1) / np.sqrt(county_paths.size),
        "model_load_se": mean_se(burn_payoffs, bootstrap_counts),
    }
    if station is None:
        metrics["hedge_ratio"] = np.full(len(specs), np.nan)
        metrics["hedged_expected_payout"] = np.full(len(specs), np.nan)
        metrics["hedged_expected_payout_se"] = np.full(len(specs), np.nan)
        metrics["residual_es_95"] = np.full(len(specs), np.nan)
        return metrics
    ratios = hedge_ratios(county_paths, station, specs)
    station_paths = _paths(station, name="station")
    centered = station_paths - station_paths.mean()
    residual = county_payoffs - ratios[:, None] * centered[None, :]
    metrics["hedge_ratio"] = ratios
    metrics["hedged_expected_payout"] = residual.mean(axis=1)
    # The station leg is centered by this same sample's mean.  It therefore
    # sums to zero exactly, so this is the physical-mean estimator, not an
    # externally calibrated control-variate estimator.  Residual dispersion is
    # retained below for tail risk, but cannot reduce the mean's MC uncertainty.
    metrics["hedged_expected_payout_se"] = metrics["expected_payout_se"].copy()
    tail = max(1, int(np.ceil(0.05 * county_paths.size)))
    metrics["residual_es_95"] = np.partition(residual, -tail, axis=1)[:, -tail:].mean(axis=1)
    return metrics


def compare_independent_seed_metrics(
    primary: dict[str, np.ndarray], secondary: dict[str, np.ndarray], *, sigma: float = 4.0
) -> dict[str, object]:
    """Compare two labelled, independently generated quote batches.

    The caller owns artifact identity checks (model, seed, panel and ticket
    specification).  This numerical kernel checks the two estimated means
    against their independent Monte Carlo uncertainty and retains hedge/load/
    tail values as diagnostics rather than claiming that common randomness
    proves agreement.
    """
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError("sigma must be finite and positive")
    checks = (
        ("expected_payout", "expected_payout_se"),
        ("hedged_expected_payout", "hedged_expected_payout_se"),
    )
    diagnostics = ("model_load_se", "hedge_ratio", "residual_es_95")
    rows: list[dict[str, object]] = []
    passed = True
    for value_key, se_key in checks:
        left = np.asarray(primary[value_key], dtype=float)
        right = np.asarray(secondary[value_key], dtype=float)
        left_se = np.asarray(primary[se_key], dtype=float)
        right_se = np.asarray(secondary[se_key], dtype=float)
        if left.shape != right.shape or left.shape != left_se.shape or left.shape != right_se.shape:
            raise ValueError(f"independent seed metric shape mismatch for {value_key}")
        finite = (
            np.isfinite(left).all()
            and np.isfinite(right).all()
            and np.isfinite(left_se).all()
            and np.isfinite(right_se).all()
        )
        if not finite:
            raise ValueError(f"independent seed metric is non-finite for {value_key}")
        tolerance = sigma * np.hypot(left_se, right_se)
        for ticket, (a, b, limit) in enumerate(zip(left, right, tolerance, strict=True)):
            ok = abs(a - b) <= limit
            passed &= bool(ok)
            rows.append(
                {
                    "metric": value_key,
                    "ticket": ticket,
                    "primary": float(a),
                    "secondary": float(b),
                    "abs_difference": float(abs(a - b)),
                    "tolerance": float(limit),
                    "status": "passed" if ok else "failed",
                }
            )
    for key in diagnostics:
        left, right = np.asarray(primary[key], dtype=float), np.asarray(secondary[key], dtype=float)
        if left.shape != right.shape or not (np.isfinite(left).all() and np.isfinite(right).all()):
            raise ValueError(f"independent seed diagnostic mismatch for {key}")
        for ticket, (a, b) in enumerate(zip(left, right, strict=True)):
            rows.append(
                {
                    "metric": key,
                    "ticket": ticket,
                    "primary": float(a),
                    "secondary": float(b),
                    "abs_difference": float(abs(a - b)),
                    "tolerance": None,
                    "status": "diagnostic",
                }
            )
    return {"status": "passed" if passed else "failed", "sigma": sigma, "checks": rows}


def _artifact_directory(path: Path) -> Path:
    directory = Path(path)
    if directory.name == "manifest.json":
        directory = directory.parent
    if not (directory / "manifest.json").is_file():
        raise FileNotFoundError(f"missing R2j manifest: {directory / 'manifest.json'}")
    return directory


def _declared_seed(manifest: dict[str, object]) -> object:
    scenario = manifest.get("scenario_set", {})
    for source in (manifest, scenario if isinstance(scenario, dict) else {}):
        for key in ("seed_id", "random_seed", "seed"):
            if source.get(key) is not None:
                return source[key]
    # Some streamed R2j artifacts publish the reproducible random-plan content
    # ID instead of the raw integer. It is still a declared seed identifier and
    # avoids requiring an implementation-only seed field at verification time.
    if isinstance(scenario, dict) and scenario.get("common_random_plan_id"):
        return {
            "seed_schema_version": scenario.get("seed_schema_version"),
            "common_random_plan_id": scenario["common_random_plan_id"],
        }
    raise ValueError("R2j manifest lacks a declared seed identifier")


def _matrix(directory: Path, filename: str) -> tuple[np.ndarray, tuple[str, ...]]:
    with np.load(directory / filename, allow_pickle=False) as archive:
        values = np.asarray(archive["values"], dtype=np.float64)
        entities = tuple(str(value) for value in archive["entity_ids"])
        scenario_ids = tuple(str(value) for value in archive["scenario_ids"])
    if values.ndim != 2 or values.shape != (len(scenario_ids), len(entities)):
        raise ValueError(f"invalid scenario matrix: {directory / filename}")
    if not np.isfinite(values).all():
        raise ValueError(f"non-finite scenario matrix: {directory / filename}")
    return values, entities


def verify_seed_artifacts(primary: Path, secondary: Path) -> dict[str, object]:
    """Run B10's bounded independent-seed quote comparison from frozen artifacts.

    This reads two explicitly supplied artifacts only.  It neither starts a
    weather fit nor extends a scenario run.  The bounded panel must have the
    same labelled county/pair and station/pair support under distinct declared
    seeds and random plans.
    """
    primary_dir, secondary_dir = _artifact_directory(primary), _artifact_directory(secondary)
    left = json.loads((primary_dir / "manifest.json").read_text())
    right = json.loads((secondary_dir / "manifest.json").read_text())
    if left.get("kind") != "r2j-production-stream" or right.get("kind") != "r2j-production-stream":
        raise ValueError("seed validation requires two R2j production-stream artifacts")
    left_scenario, right_scenario = left["scenario_set"], right["scenario_set"]
    comparable = (
        ("schema_version", left, right),
        ("data_vintage_id", left_scenario, right_scenario),
        ("generator_spec_id", left_scenario, right_scenario),
        ("location_ids", left_scenario, right_scenario),
        ("model_spec_ids", left_scenario, right_scenario),
        ("fit_id", left, right),
        ("fit_request", left, right),
        ("observation_cutoff", left, right),
        ("bridge_days", left, right),
        ("accumulation_dates", left, right),
        ("source_hashes", left, right),
        ("pair_order", left, right),
    )
    for name, first, second in comparable:
        if canonical_json(first.get(name)) != canonical_json(second.get(name)):
            raise ValueError(f"independent seed artifact mismatch: {name}")
    primary_seed, secondary_seed = _declared_seed(left), _declared_seed(right)
    if canonical_json(primary_seed) == canonical_json(secondary_seed):
        raise ValueError("independent seed artifacts declare the same seed")
    for field in ("common_random_plan_id",):
        if left_scenario.get(field) == right_scenario.get(field):
            raise ValueError(f"independent seed artifacts share {field}")
    if left.get("row_plan_sha256") == right.get("row_plan_sha256"):
        raise ValueError("independent seed artifacts share row_plan_sha256")
    if set(left["county_chunks"]) != set(right["county_chunks"]):
        raise ValueError("independent seed county panel labels differ")
    left_station, station_entities = _matrix(primary_dir, str(left["station_chunk"]))
    right_station, right_station_entities = _matrix(secondary_dir, str(right["station_chunk"]))
    if (
        left_station.shape[0] != right_station.shape[0]
        or station_entities != right_station_entities
    ):
        raise ValueError("independent seed station scenario support differs")
    pairs = tuple(str(value) for value in left["pair_order"])
    import pandas as pd

    from weather_basis.hedge.asof import current_pair

    root = primary_dir
    registry_path = root / "data" / "metadata" / "station_registry.csv"
    while root != root.parent and not registry_path.is_file():
        root = root.parent
        registry_path = root / "data" / "metadata" / "station_registry.csv"
    if not registry_path.is_file():
        raise FileNotFoundError("cannot locate repository station registry for B10 selection")
    station_ids = tuple(
        pd.read_csv(registry_path).iloc[:13].ghcnd_id.astype(str)
    )
    selections = {pair: current_pair(root, pair, modeled_station_ids=station_ids) for pair in pairs}
    metrics_left: list[dict[str, np.ndarray]] = []
    metrics_right: list[dict[str, np.ndarray]] = []
    panel: list[dict[str, str]] = []
    ticket_specs: list[dict[str, object]] = []
    from weather_basis.pricing.bootstrap import year_counts

    for fips in sorted(left["county_chunks"]):
        left_county, entities = _matrix(primary_dir, str(left["county_chunks"][fips]))
        right_county, right_entities = _matrix(secondary_dir, str(right["county_chunks"][fips]))
        if entities != right_entities or left_county.shape != right_county.shape:
            raise ValueError(f"independent seed county scenario support differs: {fips}")
        for entity_index, entity in enumerate(entities):
            entity_fips, pair = entity.split(":", 1)
            if entity_fips != fips or pair not in selections:
                raise ValueError(f"unexpected county scenario entity: {entity}")
            selected = selections[pair][fips]["station_id"]
            station_entity = f"{selected}:{pair}" if selected else None
            if station_entity not in station_entities:
                raise ValueError(
                    f"selected station lacks independent scenario support: {fips}/{pair}"
                )
            burn_table = pd.read_parquet(root / "results/indices" / f"county_{pair}.parquet")
            burn = burn_table.loc[
                burn_table.fips.astype(str).str.zfill(5).eq(fips)
            ].sort_values("season").index.to_numpy(dtype=float)[-30:]
            if burn.size < 2 or not np.isfinite(burn).all():
                raise ValueError(f"insufficient finite burn history: {fips}/{pair}")
            strikes = np.quantile(burn, (0.25, 0.5, 0.75))
            specs = tuple(
                V2Payoff(kind, strike=float(strike), multiplier=20.0)
                for strike in strikes
                for kind in ("call", "put")
            )
            counts = year_counts(
                burn.size, 200, np.random.SeedSequence((20260905, int(fips), entity_index))
            )
            station_index = station_entities.index(station_entity)
            metrics_left.append(
                batch_quote_metrics(
                    left_county[:, entity_index],
                    left_station[:, station_index],
                    burn,
                    specs,
                    counts,
                )
            )
            metrics_right.append(
                batch_quote_metrics(
                    right_county[:, entity_index],
                    right_station[:, station_index],
                    burn,
                    specs,
                    counts,
                )
            )
            panel.append({"fips": fips, "pair": pair, "station_entity": station_entity})
            ticket_specs.extend(
                {
                    "fips": fips,
                    "pair": pair,
                    "kind": spec.kind,
                    "strike": spec.strike,
                    "cap": spec.cap,
                    "multiplier": spec.multiplier,
                }
                for spec in specs
            )

    def flatten(values: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
        return {key: np.concatenate([item[key] for item in values]) for key in values[0]}

    comparison = compare_independent_seed_metrics(flatten(metrics_left), flatten(metrics_right))
    return {
        "status": comparison["status"],
        "primary": {
            "manifest": str(primary_dir / "manifest.json"),
            "sha256": file_sha256(primary_dir / "manifest.json"),
            "seed": primary_seed,
            "scenario_set_id": left_scenario["scenario_set_id"],
        },
        "secondary": {
            "manifest": str(secondary_dir / "manifest.json"),
            "sha256": file_sha256(secondary_dir / "manifest.json"),
            "seed": secondary_seed,
            "scenario_set_id": right_scenario["scenario_set_id"],
        },
        "panel_id": content_id(panel, prefix="b10-panel"),
        "ticket_spec_id": content_id(ticket_specs, prefix="b10-tickets"),
        "panel": panel,
        "ticket_specs": ticket_specs,
        "n_county_pairs": len(panel),
        "n_tickets": len(ticket_specs),
        "comparison": comparison,
    }
