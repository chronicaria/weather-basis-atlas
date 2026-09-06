"""Streamed, fixed-global-plan scenario artifacts."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import numpy as np

from weather_basis.contracts.calendar import PAIRS
from weather_basis.contracts.registry import load_frozen_vintage
from weather_basis.provenance.ids import content_id

from .common import build_historical_common_years, build_trend_bootstrap, monthly_degree_day_matrix
from .global_plan import build_global_season_plan

DEFAULT_REPRESENTATIVE_COUNTIES = ("31055", "31109", "31079", "31111", "31157", "06037", "36061")


def _research_value(research: object, name: str, default: object) -> object:
    return (
        research.get(name, default)
        if isinstance(research, dict)
        else getattr(research, name, default)
    )


def _write_matrix(path: Path, matrix) -> None:
    np.savez_compressed(
        path,
        values=matrix.values,
        scenario_ids=np.asarray(matrix.scenario_ids),
        entity_ids=np.asarray(matrix.entity_ids),
        parent_scenario_set_id=np.asarray([matrix.parent_scenario_set_id]),
        units=np.asarray([matrix.units]),
    )


def _source_hashes(plan, vintage) -> dict[str, str]:
    return {name: digest for name, digest in plan.source_hashes} | {
        "vintage_lock": vintage.data_vintage_sha256
    }


def build_from_frozen(
    root: Path | str,
    out: Path | str,
    research: object,
    county_ids: tuple[str, ...] | None = None,
    paths: int | None = None,
) -> dict[str, object]:
    """Build a representative artifact under the release-wide global source plan."""
    return build_national(
        root, out, research, county_ids=county_ids or DEFAULT_REPRESENTATIVE_COUNTIES, paths=paths
    )


def build_national(
    root: Path | str,
    out: Path | str,
    research: object,
    county_ids: tuple[str, ...] | None = None,
    paths: int | None = None,
) -> dict[str, object]:
    """Write compact chunks without materializing a national daily cube.

    The 10k source-season plan is calculated against all 3,107 county series
    plus all frozen station series. Every chunk uses a prefix of its one draw
    sequence, so no county can reseed or silently lose support.
    """
    root, out = Path(root), Path(out)
    offline = int(_research_value(research, "offline_paths", 10_000))
    public = int(_research_value(research, "public_paths", 2_000))
    count = int(paths if paths is not None else public)
    if not (1 <= count <= public <= offline or count == offline):
        raise ValueError("requested paths must be a public prefix or the full offline plan")
    global_plan = build_global_season_plan(
        root,
        offline_paths=offline,
        valuation_asof=str(_research_value(research, "valuation_asof", "2026-07-01")),
        seed=int(_research_value(research, "seed", 20260905)),
        horizon_start=str(_research_value(research, "horizon_start", "2026-07-01")),
        horizon_end=str(_research_value(research, "horizon_end", "2027-06-30")),
    )
    # A 512-path run is a validation prefix. The public release is exactly the
    # first declared 2,000 draws of this same offline plan.
    source_seasons = global_plan.public_seasons(count)
    common = replace(global_plan.common_plan, scenario_count=count)
    panel = root / "data" / "panel"
    fips = tuple(
        str(item) for item in np.load(panel / "fips.npy", mmap_mode="r", allow_pickle=False)
    )
    lookup = {fips_value: index for index, fips_value in enumerate(fips)}
    requested = tuple(str(item) for item in (county_ids or fips))
    absent = tuple(item for item in requested if item not in lookup)
    if absent:
        raise ValueError(f"requested counties lack frozen-panel support: {absent}")
    dates = np.load(panel / "dates.npy", mmap_mode="r", allow_pickle=False)
    counties = np.load(panel / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)
    stations = np.load(panel / "stations_tbar_f32.npy", mmap_mode="r", allow_pickle=False)
    station_ids = tuple(
        str(item) for item in np.load(panel / "station_ids.npy", mmap_mode="r", allow_pickle=False)
    )
    vintage = load_frozen_vintage(root)
    out.mkdir(parents=True, exist_ok=True)
    started = perf_counter()

    station_paths = build_trend_bootstrap(
        dates=dates,
        values=stations,
        location_ids=station_ids,
        plan=common,
        data_vintage_id=vintage.vintage_id,
        source_seasons=global_plan.eligible_seasons,
        exact_drawn_seasons=source_seasons,
    )
    station_matrix = monthly_degree_day_matrix(station_paths)
    global_set = replace(station_paths.scenario_set, location_ids=global_plan.location_ids)
    _write_matrix(out / "stations_14pair.npz", station_matrix)

    chunks: dict[str, str] = {}
    audit_values, audit_entities = [station_paths.values[:2]], list(station_ids)
    for county in requested:
        county_paths = build_trend_bootstrap(
            dates=dates,
            values=counties[:, [lookup[county]]],
            location_ids=(county,),
            plan=common,
            data_vintage_id=vintage.vintage_id,
            source_seasons=global_plan.eligible_seasons,
            exact_drawn_seasons=source_seasons,
        )
        if county_paths.scenario_set.scenario_set_id != global_set.scenario_set_id:
            raise RuntimeError("county chunk changed the fixed global ScenarioSet parent")
        matrix = monthly_degree_day_matrix(county_paths).select(
            tuple(f"{county}:{pair.key}" for pair in PAIRS)
        )
        _write_matrix(out / f"county_{county}.npz", matrix)
        chunks[county] = f"county_{county}.npz"
        audit_values.append(county_paths.values[:2])
        audit_entities.append(county)
    np.savez_compressed(
        out / "audit_daily_paths.npz",
        values=np.concatenate(audit_values, axis=2),
        scenario_ids=np.asarray(global_set.scenario_ids[:2]),
        entity_ids=np.asarray(audit_entities),
        parent_scenario_set_id=np.asarray([global_set.scenario_set_id]),
        units=np.asarray(["degF"]),
        dates=station_paths.dates.values.astype("datetime64[D]"),
    )

    try:
        observed = build_historical_common_years(
            dates=dates,
            values=np.concatenate((counties[:, [lookup[x] for x in requested]], stations), axis=1),
            location_ids=requested + station_ids,
            plan=common,
            data_vintage_id=vintage.vintage_id,
        )
        observed_status: dict[str, object] = {
            "status": "available",
            "scenario_count": len(observed.scenario_set.scenario_ids),
        }
    except ValueError as error:
        observed_status = {"status": "unavailable", "reason": str(error)}
    manifest = {
        "schema_version": "2.0",
        "kind": "fixed-global-plan-monthly-chunks",
        "production_status": "representative-only; B20 must freeze generator before national run",
        "global_plan_id": global_plan.plan_id,
        "parent_scenario_set_id": global_set.scenario_set_id,
        "scenario_set": global_set.to_dict(),
        "offline_paths": offline,
        "public_paths": public,
        "paths": count,
        "public_slice_rule": "offline_draws[0:public_paths]; no resampling",
        "is_exact_public_release": count == public,
        "source_seasons": list(source_seasons),
        "eligible_seasons": list(global_plan.eligible_seasons),
        "source_file_hashes": _source_hashes(global_plan, vintage),
        "vintage_id": vintage.vintage_id,
        "county_chunks": chunks,
        "station_chunk": "stations_14pair.npz",
        "station_chunk_shape": list(station_matrix.values.shape),
        "pairs": [pair.key for pair in PAIRS],
        "audit_daily_paths": "audit_daily_paths.npz",
        "observed_common_year_support": observed_status,
        "elapsed_seconds": perf_counter() - started,
    }
    manifest["artifact_id"] = content_id(
        {key: value for key, value in manifest.items() if key != "elapsed_seconds"}
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
