# ruff: noqa: E501, E701, E702
"""Bounded real-data B20 experiments.

This module deliberately separates a representative Nebraska decision study
from the later, frozen national production run.  Every choice is recomputed
from years strictly before its origin; it never uses the realized origin to
choose stations or basket coefficients.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from weather_basis.provenance.artifacts import make_manifest, publish_directory
from weather_basis.provenance.ids import content_id, file_sha256

NEBRASKA = {
    "Omaha": ("31055", "USW00014942"),
    "Lincoln": ("31109", "USW00014939"),
    "Grand Island": ("31079", "USW00014935"),
    "North Platte": ("31111", "USW00024023"),
    "Scottsbluff": ("31157", "USW00024028"),
}


def _read_pair(root: Path, pair: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    county = pd.read_parquet(root / "results" / "indices" / f"county_{pair}.parquet")
    station = pd.read_parquet(root / "results" / "indices" / f"station_{pair}.parquet")
    county["fips"] = county["fips"].astype(str).str.zfill(5)
    return county, station


def _matrix(frame: pd.DataFrame, item: str, ids: list[str], years: np.ndarray) -> np.ndarray:
    pivot = frame.pivot(index=item, columns="season", values="index").reindex(index=ids, columns=years)
    return pivot.to_numpy(dtype=float)


def _fit(y: np.ndarray, x: np.ndarray, maximum: int) -> tuple[np.ndarray, float, tuple[int, ...]] | None:
    corrs = []
    for j in range(x.shape[1]):
        finite_j = np.isfinite(y) & np.isfinite(x[:, j])
        corrs.append(np.corrcoef(y[finite_j], x[finite_j, j])[0, 1] if finite_j.sum() >= 8 and np.std(x[finite_j, j]) else np.nan)
    corrs = np.asarray(corrs)
    chosen = tuple(np.flatnonzero(np.isfinite(corrs))[np.argsort(corrs[np.isfinite(corrs)])[-maximum:]].tolist())
    if not chosen:
        return None
    finite = np.isfinite(y) & np.isfinite(x[:, chosen]).all(axis=1)
    if finite.sum() < max(8, len(chosen) + 3):
        return None
    yy, xx = y[finite], x[finite]
    design = np.column_stack([np.ones(finite.sum()), xx[:, chosen]])
    coef = np.linalg.lstsq(design, yy, rcond=None)[0]
    return coef[1:], float(coef[0]), chosen


def _prediction(y: np.ndarray, stations: np.ndarray, train: np.ndarray, at: int, maximum: int) -> tuple[float, tuple[int, ...], np.ndarray] | None:
    fitted = _fit(y[train], stations[train], maximum)
    if fitted is None or not np.isfinite(y[at]):
        return None
    coef, intercept, chosen = fitted
    if not np.isfinite(stations[at, list(chosen)]).all():
        return None
    return float(y[at] - (intercept + stations[at, list(chosen)] @ coef)), chosen, coef


def _bootstrap_mean(values: np.ndarray, seed: int = 20260905, draws: int = 1000) -> list[float | None]:
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    means = np.mean(rng.choice(values, size=(draws, len(values)), replace=True), axis=1)
    return [float(np.quantile(means, .025)), float(np.quantile(means, .975))]


def _risk(values: np.ndarray, alpha: float) -> dict[str, float | None]:
    values = values[np.isfinite(values)]
    if not len(values):
        return {"n": 0, "mse": None, "es": None}
    squared = values**2
    tail = squared[squared >= np.quantile(squared, alpha)]
    return {"n": int(len(values)), "mse": float(np.mean(squared)), "es": float(np.mean(tail))}


def _r02(root: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for pair in cfg["common"]["pairs"]:
        county, station = _read_pair(root, pair)
        years = np.arange(1951, 2027)
        station_ids = sorted(station.ghcnd_id.unique())
        sm = _matrix(station, "ghcnd_id", station_ids, years).T
        for place, (fips, local) in NEBRASKA.items():
            y = _matrix(county, "fips", [fips], years)[0]
            for origin in cfg["common"]["outer_origins"]:
                at = int(np.where(years == origin)[0][0])
                train = np.flatnonzero(years < origin)
                if len(train) < cfg["common"]["min_training_years"]:
                    continue
                # Nearest here means the registered local station, when observed.
                local_i = station_ids.index(local)
                near = _prediction(y, sm[:, [local_i]], train, at, 1)
                basket = _prediction(y, sm, train, at, 3)
                if near is None or basket is None:
                    continue
                nr, _, _ = near
                br, chosen, coefficients = basket
                rows.append({"experiment": "R02", "pair": pair, "place": place, "fips": fips,
                             "origin": origin, "nearest_residual": nr, "basket_residual": br,
                             "squared_loss_change": br**2 - nr**2,
                             "basket_stations": "|".join(station_ids[i] for i in chosen),
                             "basket_coefficients": "|".join(f"{x:.8g}" for x in coefficients)})
    frame = pd.DataFrame(rows)
    summary: list[dict[str, Any]] = []
    for keys, group in frame.groupby(["pair", "place"], sort=True):
        near, basket = _risk(group.nearest_residual.to_numpy(), cfg["common"]["tail_level"]), _risk(group.basket_residual.to_numpy(), cfg["common"]["tail_level"])
        change = group.squared_loss_change.to_numpy()
        ci = _bootstrap_mean(change)
        summary.append({"pair": keys[0], "place": keys[1], "origins": int(len(group)), "nearest": near,
                        "basket": basket, "mean_paired_squared_loss_change": float(change.mean()),
                        "paired_mean_ci95": ci,
                        "top_basket_frequency": group.basket_stations.value_counts().head(1).to_dict(),
                        "disposition": "representative_improvement_needs_confirmation" if ci[1] is not None and ci[1] < 0 else "inconclusive_or_retain_simple"})
    return {"experiment": "R02", "scope": "five Nebraska county/station mappings; actual annual index panels", "results": summary}, rows


def _r03(root: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Same realized county-year coordinates, fixed total five-station constraint.

    This is an observed historical book evaluation, deliberately distinct from
    B11's predictive common-scenario experiment.  It is useful evidence about
    the selection rule, but cannot establish prospective joint tail behavior.
    """
    rows: list[dict[str, Any]] = []
    for pair in cfg["common"]["pairs"]:
        county, station = _read_pair(root, pair); years = np.arange(1951, 2027)
        fipses = [value[0] for value in NEBRASKA.values()]
        y = _matrix(county, "fips", fipses, years)
        ids = sorted(station.ghcnd_id.unique()); x = _matrix(station, "ghcnd_id", ids, years).T
        for origin in cfg["common"]["outer_origins"]:
            at = int(np.where(years == origin)[0][0]); train = np.flatnonzero(years < origin)
            if len(train) < cfg["common"]["min_training_years"] or not np.isfinite(y[:, at]).all():
                continue
            separate = []
            for target in y:
                prediction = _prediction(target, x, train, at, 1)
                if prediction is None:
                    separate = []; break
                residual, _, coefficients = prediction
                separate.append(residual + cfg["common"]["assumed_cost"] * np.abs(coefficients).sum())
            joint = _prediction(y.sum(axis=0), x, train, at, 5)
            if not separate or joint is None:
                continue
            joint_residual, chosen, coefficients = joint
            joint_residual += cfg["common"]["assumed_cost"] * np.abs(coefficients).sum()
            rows.append({"experiment": "R03", "pair": pair, "origin": int(origin),
                         "separate_book_loss": float(sum(separate)), "joint_book_loss": float(joint_residual),
                         "squared_loss_change": float(joint_residual**2 - sum(separate)**2),
                         "joint_stations": "|".join(ids[i] for i in chosen), "status": "observed_common_year"})
    summary = []
    for pair, group in pd.DataFrame(rows).groupby("pair", sort=True):
        separate, joint = _risk(group.separate_book_loss.to_numpy(), cfg["common"]["tail_level"]), _risk(group.joint_book_loss.to_numpy(), cfg["common"]["tail_level"])
        changes = group.squared_loss_change.to_numpy()
        summary.append({"pair": pair, "origins": int(len(group)), "separate": separate, "joint": joint,
                        "mean_paired_squared_loss_change": float(changes.mean()), "paired_mean_ci95": _bootstrap_mean(changes),
                        "disposition": "observed_joint_improvement_needs_B11_confirmation" if changes.mean() < 0 else "retain_separate_or_inconclusive"})
    return {"experiment": "R03", "scope": "chronological five-county observed-index book; same maximum five-station total constraint; not a B11 predictive common-scenario result", "results": summary}, rows


def _he(y: np.ndarray, residual: np.ndarray) -> float | None:
    ok = np.isfinite(y) & np.isfinite(residual)
    if ok.sum() < 2:
        return None
    den = float(np.sum((y[ok] - np.mean(y[ok])) ** 2))
    return None if den <= 1e-12 else float(1 - np.sum(residual[ok] ** 2) / den)


def _r05(root: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    # Bounded national screen: two chronological windows x source-defined 13/18 candidates.
    windows = ((1981, 2005, 2006, 2025), (1991, 2010, 2011, 2025))
    for pair in cfg["common"]["pairs"]:
        county, station = _read_pair(root, pair); years = np.arange(1951, 2027)
        counties = sorted(county.fips.unique()); ids = sorted(station.ghcnd_id.unique())
        ymat = _matrix(county, "fips", counties, years); smat = _matrix(station, "ghcnd_id", ids, years).T
        role = pd.read_csv(root / "data" / "metadata" / "station_registry.csv").set_index("ghcnd_id").role.to_dict()
        for universe, candidates in (("cme13", [x for x in ids if role.get(x) == "cme"]), ("extended18", ids)):
            xi = [ids.index(x) for x in candidates]
            for start, end, eval_start, eval_end in windows:
                train = (years >= start) & (years <= end); test = (years >= eval_start) & (years <= eval_end)
                for c, fips in enumerate(counties):
                    fit = _fit(ymat[c, train], smat[train][:, xi], 1)
                    if fit is None:
                        continue
                    coef, intercept, chosen = fit; j = xi[chosen[0]]
                    residual = ymat[c, test] - (intercept + smat[test, j] * coef[0])
                    value = _he(ymat[c, test], residual)
                    rows.append({"experiment": "R05", "pair": pair, "fips": fips, "universe": universe,
                                 "train_window": f"{start}-{end}", "evaluation_window": f"{eval_start}-{eval_end}",
                                 "selected_station": ids[j], "he": value, "n_evaluation": int(np.isfinite(residual).sum())})
    frame = pd.DataFrame(rows)
    grouped = frame.groupby(["pair", "fips"], sort=True).he.agg(["count", "min", "max", "mean"]).reset_index()
    grouped["classification"] = np.where(grouped["count"] < 4, "insufficient_support", np.where(grouped["max"] <= 0, "robustly_difficult", np.where(grouped["min"] <= 0, "ambiguous", "positive_in_screen")))
    report = {"experiment": "R05", "scope": "bounded national sensitivity screen, not B24 national validation", "settings": 4,
              "classification_counts": grouped.classification.value_counts().to_dict(),
              "disposition": "descriptive sensitivity only; final policy awaits corrected national policy/scenario artifacts"}
    return report, rows + [{"experiment": "R05-summary", **x} for x in grouped.to_dict("records")]


def run_research(root: Path, out: Path | None = None, *, experiments: tuple[str, ...] = ("R02", "R03", "R05")) -> dict[str, str]:
    """Run registered bounded experiments and atomically publish immutable reports."""
    root = Path(root); out = Path(out or root / "results" / "v2" / "experiments")
    config_path = root / "config" / "research" / "experiments-v2.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    protocol_id = content_id(cfg)
    r02, r02_rows = _r02(root, cfg) if "R02" in experiments or "R03" in experiments else ({}, [])
    work: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    if "R02" in experiments: work["R02"] = r02, r02_rows
    if "R03" in experiments: work["R03"] = _r03(root, cfg)
    if "R05" in experiments: work["R05"] = _r05(root, cfg)
    output: dict[str, str] = {}
    for name, (report, rows) in work.items():
        stage = f"research-{name.lower()}"; analysis_id = content_id({"protocol": protocol_id, "experiment": name})
        destination = out / name / f"{analysis_id.split(':', 1)[1][:16]}-kernel3"
        if destination.exists():
            output[name] = str(destination); continue
        (out / name).mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=out / name))
        try:
            (staging / "report.json").write_text(json.dumps({**report, "protocol_id": protocol_id}, indent=2, sort_keys=True) + "\n")
            pd.DataFrame(rows).to_parquet(staging / "rows.parquet", index=False)
            manifest = make_manifest(staging, stage_id=stage, analysis_id=analysis_id,
                execution_id=f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}", producer_fingerprint="weather_basis.research.run:v3",
                inputs={"protocol": file_sha256(config_path), "county_hdd": file_sha256(root / "results/indices/county_HDD-01.parquet"), "county_cdd": file_sha256(root / "results/indices/county_CDD-07.parquet")},
                telemetry={"rows": len(rows), "scope": report["scope"]})
            publish_directory(staging, destination, manifest); output[name] = str(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True); raise
    if "R02" in work:
        # A reusable case artifact is intentionally projected from the R02 rows,
        # so it cannot drift into hand-written favorable prose.
        case_root = out.parent / "cases" / "nebraska"
        case_id = content_id({"protocol": protocol_id, "case": "nebraska", "source": "R02"}).split(":", 1)[1][:16]
        case_destination = case_root / f"{case_id}-kernel3"
        if not case_destination.exists():
            case_root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".nebraska-", dir=case_root))
            try:
                case_rows = pd.DataFrame(r02_rows)
                metadata = pd.read_csv(root / "data" / "metadata" / "counties.csv", dtype={"fips": str}).set_index("fips")
                mapping = [{"place": place, "fips": fips, "county": metadata.loc[fips, "name"], "station": station}
                           for place, (fips, station) in NEBRASKA.items()]
                (staging / "case.json").write_text(json.dumps({"case": "Nebraska", "protocol_id": protocol_id,
                    "mapping": mapping, "scope": "HDD-01 and CDD-07; local station baseline versus prior-only sparse basket",
                    "interpretation": "Includes all five locations and retains inconclusive outcomes."}, indent=2, sort_keys=True) + "\n")
                case_rows.to_parquet(staging / "results.parquet", index=False)
                manifest = make_manifest(staging, stage_id="case-nebraska", analysis_id=content_id({"protocol": protocol_id, "case": "nebraska"}),
                    execution_id=f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}", producer_fingerprint="weather_basis.research.run:v3",
                    inputs={"protocol": file_sha256(config_path)}, telemetry={"rows": len(case_rows), "locations": 5})
                publish_directory(staging, case_destination, manifest)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True); raise
        output["Nebraska"] = str(case_destination)
    return output
