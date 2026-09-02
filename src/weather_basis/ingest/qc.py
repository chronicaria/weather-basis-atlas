"""Reproducible production-data QC reports for build-plan Section 4.6.

The reports are deliberately derived from frozen panels, raw station snapshots,
and the canonical county dimension.  They do not inspect fit statistics or
atlas results, keeping confidence and source-quality evidence independent of
the downstream hedge calculation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_basis.ingest.confidence import assess_confidence, load_ghcnd_inventory
from weather_basis.ingest.geography import (
    reconcile_fips,
    write_geography_population_manifests,
)
from weather_basis.ingest.ghcnd import parse_station, qc_station, to_integer_f
from weather_basis.io import atomic_write_bytes


def build_qc_reports(root: Path, cfg: Any) -> list[Path]:
    """Regenerate every data-QC report and source-provenance JSON artifact."""

    root = Path(root)
    qc_dir = root / "results/qc"
    qc_dir.mkdir(parents=True, exist_ok=True)
    dates = np.load(root / "data/panel/dates.npy", mmap_mode="r", allow_pickle=False)
    tavg = np.load(root / "data/panel/tavg_f32.npy", mmap_mode="r", allow_pickle=False)
    counties = pd.read_csv(root / "data/metadata/counties.csv", dtype={"fips": str})
    registry = pd.read_csv(root / "data/metadata/station_registry.csv", dtype={"ghcnd_id": str})
    station_qc = pd.read_parquet(root / "data/panel/station_qc.parquet")

    outputs = [
        _write_panel_tavg(qc_dir / "panel_tavg.json", dates, tavg),
        _write_panel_consistency(root, qc_dir, dates, tavg),
        _write_station_qc(qc_dir / "stations.json", root, registry, station_qc, cfg),
        _write_geography_qc(qc_dir / "geography.json", root, counties),
        _write_confidence(qc_dir / "confidence.json", root, counties, dates, tavg),
        _write_data_through(qc_dir / "data_through.json", dates),
    ]
    outputs.extend(write_geography_population_manifests(root))
    return outputs


def _write_panel_tavg(path: Path, dates: np.ndarray, values: np.ndarray) -> Path:
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    per_year = {str(int(year)): int((years == year).sum()) for year in np.unique(years)}
    january_2023 = (dates >= np.datetime64("2023-01-01")) & (
        dates <= np.datetime64("2023-01-31")
    )
    february_2021 = (dates >= np.datetime64("2021-02-01")) & (
        dates <= np.datetime64("2021-02-28")
    )
    _write_json(
        path,
        {
            "shape": list(values.shape),
            "nan_count": int(np.isnan(values).sum()),
            "minimum_f": float(np.nanmin(values)),
            "maximum_f": float(np.nanmax(values)),
            "per_year_row_counts": per_year,
            "january_2023_county_days": int(np.isfinite(values[january_2023]).sum()),
            "february_2021_minimum_f": float(np.nanmin(values[february_2021])),
        },
    )
    return path


def _write_panel_consistency(root: Path, qc_dir: Path, dates: np.ndarray, tavg: np.ndarray) -> Path:
    tmax_path, tmin_path = root / "data/panel/tmax_f32.npy", root / "data/panel/tmin_f32.npy"
    path = qc_dir / "panel_consistency.json"
    if not tmax_path.is_file() or not tmin_path.is_file():
        _write_json(path, {"status": "not_assessed", "reason": "TMAX/TMIN panels unavailable"})
        return path
    tmax = np.load(tmax_path, mmap_mode="r", allow_pickle=False)
    tmin = np.load(tmin_path, mmap_mode="r", allow_pickle=False)
    if tmax.shape != tavg.shape or tmin.shape != tavg.shape:
        raise ValueError("TAVG/TMAX/TMIN panels do not share one date-county dimension")
    common = np.isfinite(tavg) & np.isfinite(tmax) & np.isfinite(tmin)
    if not common.any():
        _write_json(path, {"status": "not_assessed", "reason": "no common TAVG/TMAX/TMIN cells"})
        return path
    deviation = np.abs(tavg[common] - (tmax[common] + tmin[common]) / 2.0)
    common_rows = common.any(axis=1)
    _write_json(
        path,
        {
            "max_deviation_f": float(deviation.max()),
            "mean_deviation_f": float(deviation.mean()),
            "n": int(common.sum()),
            "usable_from": str(dates[common_rows][0]),
            "usable_through": str(dates[common_rows][-1]),
        },
    )
    return path


def _write_station_qc(
    path: Path, root: Path, registry: pd.DataFrame, station_qc: pd.DataFrame, cfg: Any
) -> Path:
    tolerance = float(cfg.station.integer_f_tolerance)
    result: dict[str, dict[str, object]] = {}
    for station_id in registry["ghcnd_id"].astype(str):
        monthly = station_qc[station_qc["ghcnd_id"].astype(str) == station_id]
        raw = parse_station(root / "data/raw/ghcnd" / f"{station_id}.csv")
        source_monthly = qc_station(raw, cfg).monthly
        flags = 0
        observations = 0
        for column in ("tmax_tenths_c", "tmin_tenths_c"):
            integer_f, flagged = to_integer_f(raw[column].to_numpy(), tolerance=tolerance)
            flags += int(flagged.sum())
            observations += int(np.isfinite(integer_f).sum())
        by_decade: dict[str, dict[str, int]] = {}
        for decade, group in monthly.groupby((monthly["year"].astype(int) // 10) * 10, sort=True):
            usable = group["qc_status"].isin(("complete", "gap_filled"))
            by_decade[str(int(decade))] = {
                "months": int(len(group)),
                "usable_months": int(usable.sum()),
                "excluded_months": int((group["qc_status"] == "excluded").sum()),
            }
        # Retain the historical project measure (flagged elements divided by
        # observed station-days) and expose the unambiguous element rate too.
        station_days = max(1, len(raw))
        registry_row = registry.loc[registry["ghcnd_id"].astype(str) == station_id].iloc[0]
        result[station_id] = {
            "coverage_by_decade": by_decade,
            "excluded_months": int((source_monthly["qc_status"] == "excluded").sum()),
            "gap_filled_days": int(source_monthly["n_gap_filled"].sum()),
            "integer_f_deviation_flag_rate": flags / station_days,
            "integer_f_deviation_element_rate": flags / max(1, observations),
            "integer_f_flagged_elements": flags,
            "integer_f_observed_elements": observations,
            "provisional_months": int((source_monthly["qc_status"] == "provisional").sum()),
            "first_complete_month": str(registry_row["first_complete_month"]),
            "first_test_season": int(registry_row["first_test_season"]),
        }
    _write_json(path, result)
    return path


def _write_geography_qc(path: Path, root: Path, counties: pd.DataFrame) -> Path:
    vendor = json.loads((root / "web/vendor/counties-albers-10m.json").read_text(encoding="utf-8"))
    geometries = vendor["objects"]["counties"]["geometries"]
    atlas_ids = {str(item["id"]).zfill(5) for item in geometries}
    exceptions = pd.read_csv(root / "data/metadata/county_exceptions.csv", dtype=str)
    report = reconcile_fips(set(counties["fips"].astype(str)), atlas_ids, exceptions)
    _write_json(
        path,
        {
            "matched": report.matched,
            "atlas_only": sorted(report.atlas_only),
            "nclimgrid_only": sorted(report.nclimgrid_only),
            "exceptions": sorted(report.exceptions_applied),
        },
    )
    if not report.ok or report.matched != 3107 or report.exceptions_applied != frozenset({"51678"}):
        raise ValueError("county geography reconciliation does not match the frozen CONUS universe")
    return path


def _write_confidence(
    path: Path, root: Path, counties: pd.DataFrame, dates: np.ndarray, tavg: np.ndarray
) -> Path:
    inventory = load_ghcnd_inventory(root / "data/metadata/ghcnd-inventory.txt")
    # The county panel begins in 1951, so density before the panel's support
    # cannot inform this descriptive proxy.  Freeze the displayed decades to
    # the panel era rather than inheriting nineteenth-century inventory rows.
    report = assess_confidence(counties, inventory, tavg, dates, decades=range(1950, 2030, 10))
    frame = report.frame.sort_values("fips", kind="stable")
    _write_json(
        path,
        {
            "decades": list(report.decades),
            "counties": frame.to_dict(orient="records"),
            "counts": {
                str(key): int(value) for key, value in frame["confidence"].value_counts().items()
            },
        },
    )
    return path


def _write_data_through(path: Path, dates: np.ndarray) -> Path:
    _write_json(path, {"data_through": str(dates[-1])})
    return path


def _write_json(path: Path, value: object) -> None:
    atomic_write_bytes(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8"))
