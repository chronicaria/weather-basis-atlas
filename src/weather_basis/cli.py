"""Command-line orchestration for Weather Basis Atlas."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256 as sha256_digest
from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.config import config_hash, load_config
from weather_basis.contracts.calendar import PAIRS, Pair
from weather_basis.io import atomic_write_bytes, sha256, write_npy, write_parquet


def _write_stage(
    root: Path,
    cfg: object,
    stage: str,
    outputs: list[Path],
    inputs: list[Path],
    started_at: datetime,
    *,
    holdout_unlocked: bool = False,
    manifest_path: Path | None = None,
) -> None:
    from weather_basis.manifest_stage import write_stage_manifest

    write_stage_manifest(
        root,
        cfg,
        stage=stage,
        outputs=outputs,
        paths_in=inputs,
        holdout_unlocked=holdout_unlocked,
        started_at=started_at,
        manifest_path=manifest_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wba", description="Build the Weather Basis Atlas")
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser("data").add_subparsers(dest="data_command", required=True)
    migrate = data.add_parser("migrate")
    migrate.add_argument("--donor", type=Path, required=True)
    data.add_parser("verify")
    fetch = data.add_parser("fetch").add_subparsers(dest="fetch_command", required=True)
    fetch_grid = fetch.add_parser("nclimgrid")
    fetch_grid.add_argument("--variable", choices=("tavg", "tmax", "tmin"), required=True)
    fetch_grid.add_argument("--start", required=True, metavar="YYYY-MM")
    fetch_grid.add_argument("--end", required=True, metavar="YYYY-MM")
    for name in ("ghcnd", "homr", "geography", "population", "geocode"):
        fetch.add_parser(name)
    extend = data.add_parser("extend")
    extend.add_argument("--through", required=True, metavar="YYYY-MM")
    extend.add_argument("--decision", type=Path, required=True)
    panel = data.add_parser("panel")
    panel.add_argument(
        "--variable", choices=("tavg", "tmax", "tmin", "stations", "mean_blocks"), required=True
    )
    data.add_parser("qc")
    snapshot = data.add_parser("snapshot").add_subparsers(dest="snapshot_command", required=True)
    export = snapshot.add_parser("export")
    export.add_argument("--out", type=Path, required=True)
    import_ = snapshot.add_parser("import")
    import_.add_argument("--from", dest="source", type=Path, required=True)
    commands.add_parser("contracts").add_subparsers(
        dest="contracts_command", required=True
    ).add_parser("check")
    indices = (
        commands.add_parser("indices")
        .add_subparsers(dest="indices_command", required=True)
        .add_parser("build")
    )
    indices.add_argument("--pairs", nargs="*")
    atlas = commands.add_parser("atlas").add_subparsers(dest="atlas_command", required=True)
    atlas_run = atlas.add_parser("run")
    atlas_run.add_argument("--pairs", nargs="*")
    atlas_run.add_argument("--fixture", action="store_true")
    atlas.add_parser("headline")
    models = commands.add_parser("models").add_subparsers(dest="models_command", required=True)
    model_fit = models.add_parser("fit")
    model_fit.add_argument("--origins", default="1991-2022")
    models.add_parser("tournament")
    model_simulate = models.add_parser("simulate")
    model_simulate.add_argument("--as-of", default="site")
    commands.add_parser("quotes").add_subparsers(dest="quotes_command", required=True).add_parser(
        "build"
    )
    commands.add_parser("nebraska").add_subparsers(
        dest="nebraska_command", required=True
    ).add_parser("run")
    site = commands.add_parser("site").add_subparsers(dest="site_command", required=True)
    for name in ("payloads", "build", "check", "serve"):
        item = site.add_parser(name)
        item.add_argument("--out", "--site", dest="site_path", type=Path, default=Path("site"))
        item.add_argument("--fixture", action="store_true")
    reproduce = commands.add_parser("reproduce")
    reproduce.add_argument("--fixture", action="store_true")
    reproduce.add_argument("--snapshot", type=Path)
    reproduce.add_argument("--out", type=Path, required=True)
    gate = commands.add_parser("gate")
    gate.add_argument("number", type=int, choices=range(8))
    return parser


def _selected_pairs(keys: list[str] | None) -> tuple[Pair, ...]:
    if not keys:
        return PAIRS
    mapping = {pair.key: pair for pair in PAIRS}
    unknown = sorted(set(keys) - set(mapping))
    if unknown:
        raise ValueError(f"Unknown contract pair(s): {', '.join(unknown)}")
    return tuple(mapping[key] for key in keys)


def _months(start: tuple[int, int], end: tuple[int, int]):
    from weather_basis.ingest.nclimgrid import Month

    year, month = start
    while (year, month) <= end:
        yield Month(year, month)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _run_data(args: argparse.Namespace, root: Path) -> int:
    from weather_basis.ingest.migrate import export_snapshot, import_snapshot, migrate_legacy
    from weather_basis.ingest.nclimgrid import verify_manifest
    from weather_basis.ingest.panel import build_panel

    if args.data_command == "migrate":
        report = migrate_legacy(args.donor, root)
        print(report)
        return 0 if report.ok else 1
    if args.data_command == "verify":
        from weather_basis.ingest.migrate import verify_sha256sums, write_sha256sums

        report = verify_manifest(
            root / "data/manifests/nclimgrid_tavg.csv", root / "data/raw/nclimgrid_daily"
        )
        checksum_drift = verify_sha256sums(root) if (root / "data/raw/SHA256SUMS").exists() else ()
        if report.ok and not checksum_drift:
            write_sha256sums(root)
        print(report)
        if checksum_drift:
            print("\n".join(checksum_drift))
        return 0 if report.ok and not checksum_drift else 1
    if args.data_command == "snapshot":
        if args.snapshot_command == "export":
            report = export_snapshot(root, args.out)
            print(report)
            return 0
        report = import_snapshot(args.source, root)
        print(report)
        return 0 if report.ok else 1
    if args.data_command == "fetch":
        return _fetch_data(args, root)
    if args.data_command == "extend":
        return _extend_data(args, root)
    if args.data_command == "panel":
        if args.variable == "stations":
            return _build_station_panel(root)
        if args.variable == "mean_blocks":
            from weather_basis.models.run_daily import build_mean_blocks

            build_mean_blocks(root, load_config(root / "config/defaults.yaml"))
            return 0
        cfg = load_config(root / "config/defaults.yaml")
        start = tuple(map(int, str(cfg.panel.start).split("-")[:2]))
        end = tuple(map(int, str(cfg.panel.end).split("-")[:2]))
        report = build_panel(
            args.variable,
            list(_months(start, end)),
            root / "data/raw/nclimgrid_daily",
            root / "data/panel",
            pd.read_csv(root / "data/metadata/counties.csv", dtype=str),
        )
        print(report)
        return 0
    from weather_basis.ingest.ghcnd import backfill_station_registry
    from weather_basis.ingest.qc import build_qc_reports

    cfg = load_config(root / "config/defaults.yaml")
    backfill_station_registry(root)
    outputs = build_qc_reports(root, cfg)
    print("\n".join(str(path.relative_to(root)) for path in outputs))
    return 0


def _manifest_data_command(
    args: argparse.Namespace, root: Path, cfg: object, started_at: datetime
) -> None:
    """Write complete provenance for each successful data subcommand."""

    command = args.data_command
    if command == "migrate":
        outputs = [root / "data/raw", root / "data/manifests", root / "data/metadata"]
        inputs = [args.donor]
        stage = "data_migrate"
    elif command == "verify":
        outputs = [root / "data/raw/SHA256SUMS"]
        inputs = [root / "data/raw", root / "data/manifests"]
        stage = "data_verify"
    elif command == "snapshot":
        if args.snapshot_command == "export":
            outputs = [root / "data/raw/SHA256SUMS"]
            inputs = [args.out.resolve()]
            stage = "data_snapshot_export"
        else:
            outputs = [root / "data/raw", root / "data/manifests", root / "data/metadata"]
            inputs = [args.source.resolve()]
            stage = "data_snapshot_import"
    elif command == "extend":
        outputs = [root / "config/data_vintage.yaml"]
        inputs = [args.decision.resolve()]
        stage = "data_extend"
    elif command == "panel":
        panel_outputs: dict[str, list[Path]] = {
            "tavg": [
                root / "data/panel/tavg_f32.npy",
                root / "data/panel/dates.npy",
                root / "data/panel/fips.npy",
            ],
            "tmax": [
                root / "data/panel/tmax_f32.npy",
                root / "data/panel/dates.npy",
                root / "data/panel/fips.npy",
            ],
            "tmin": [
                root / "data/panel/tmin_f32.npy",
                root / "data/panel/dates.npy",
                root / "data/panel/fips.npy",
            ],
            "stations": [
                root / "data/panel/stations_tbar_f32.npy",
                root / "data/panel/station_ids.npy",
                root / "data/panel/station_qc.parquet",
            ],
            "mean_blocks": [root / "data/panel/mean_blocks.npz"],
        }
        outputs = panel_outputs[args.variable]
        inputs = [root / "data/raw", root / "data/metadata"]
        stage = f"data_panel_{args.variable}"
    elif command == "qc":
        from weather_basis.manifest_stage import write_data_qc_manifest

        write_data_qc_manifest(
            root,
            cfg,
            outputs=[
                root / "results/qc",
                root / "data/manifests/geography.json",
                root / "data/manifests/population.json",
            ],
            inputs=[
                root / "data/raw",
                root / "data/panel",
                root / "data/manifests",
                root / "data/metadata",
            ],
            started_at=started_at,
        )
        return
    elif command == "fetch":
        fetch_outputs: dict[str, list[Path]] = {
            "nclimgrid": [
                root / "data/raw/nclimgrid_daily",
                root / f"data/manifests/nclimgrid_{args.variable}.csv",
            ],
            "ghcnd": [root / "data/raw/ghcnd", root / "data/manifests/ghcnd_stations.csv"],
            "homr": [root / "data/raw/homr", root / "data/manifests/homr.csv"],
            "geography": [
                root / "web/vendor/counties-albers-10m.json",
                root / "data/manifests/geography.csv",
            ],
            "population": [
                root / "data/raw/census/co-est2021-alldata.csv",
                root / "data/manifests/population.csv",
            ],
            "geocode": [root / "data/contracts/station_county.csv"],
        }
        outputs = fetch_outputs[args.fetch_command]
        inputs = [root / "config/defaults.yaml"]
        stage = f"data_fetch_{args.fetch_command}"
    else:  # pragma: no cover - argparse constrains the command surface.
        raise ValueError(f"cannot manifest data command: {command}")
    _write_stage(root, cfg, stage, outputs, inputs, started_at)
    if command == "panel":
        # Retain command-specific ownership while keeping the aggregate panel
        # manifest expected by downstream consumers complete.
        _write_stage(
            root,
            cfg,
            "data_panel",
            [root / "data/panel"],
            [root / "data/raw", root / "data/metadata"],
            started_at,
        )


def _write_fetch_manifest(path: Path, results: list[object]) -> None:
    """Persist fetch responses in the plan's CSV provenance form."""

    rows: list[dict[str, object]] = []
    for result in results:
        row = dict(vars(result))
        target = Path(str(row["path"]))
        try:
            row["path"] = target.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            row["path"] = str(target)
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _fetch_data(args: argparse.Namespace, root: Path) -> int:
    """Run only the approved, explicitly selected acquisition operation."""

    command = args.fetch_command
    cfg = load_config(root / "config/defaults.yaml")
    if command == "nclimgrid":
        from weather_basis.ingest.nclimgrid import Month, fetch_month

        start, end = Month.parse(args.start), Month.parse(args.end)
        if end < start:
            raise ValueError("--end must not precede --start")
        results = [
            fetch_month(args.variable, month, root / "data/raw/nclimgrid_daily")
            for month in _months((start.year, start.month), (end.year, end.month))
        ]
        _write_fetch_manifest(root / f"data/manifests/nclimgrid_{args.variable}.csv", results)
        return 0
    if command == "ghcnd":
        from weather_basis.ingest.ghcnd import fetch_station

        results = [
            fetch_station(station_id, root / "data/raw/ghcnd") for station_id in cfg.station.ids
        ]
        _write_fetch_manifest(root / "data/manifests/ghcnd_stations.csv", results)
        return 0
    if command == "homr":
        from weather_basis.ingest.homr import fetch_station

        results = [
            fetch_station(station_id, root / "data/raw/homr") for station_id in cfg.station.ids
        ]
        _write_fetch_manifest(root / "data/manifests/homr.csv", results)
        return 0
    if command == "geography":
        from weather_basis.ingest.geography import vendor_asset

        result = vendor_asset(
            "counties-albers-10m.json",
            "https://cdn.jsdelivr.net/npm/us-atlas@3/counties-albers-10m.json",
            root / "web/vendor/counties-albers-10m.json",
        )
        _write_fetch_manifest(root / "data/manifests/geography.csv", [result])
        return 0
    if command == "population":
        from weather_basis.http import fetch

        result = fetch(
            "https://www2.census.gov/programs-surveys/popest/datasets/2020-2021/counties/totals/co-est2021-alldata.csv",
            root / "data/raw/census/co-est2021-alldata.csv",
            allow_hosts=frozenset({"www2.census.gov"}),
        )
        _write_fetch_manifest(root / "data/manifests/population.csv", [result])
        return 0
    if command == "geocode":
        from weather_basis.ingest.geography import geocode_station

        registry = pd.read_csv(root / "data/metadata/station_registry.csv")
        rows = []
        for station in registry.itertuples(index=False):
            fips, raw = geocode_station(float(station.lat), float(station.lon))
            rows.append(
                {
                    "ghcnd_id": station.ghcnd_id,
                    "county_fips": fips,
                    "response_sha256": sha256_digest(raw).hexdigest(),
                    "manual_override": "",
                }
            )
        pd.DataFrame(rows).to_csv(root / "data/contracts/station_county.csv", index=False)
        return 0
    raise ValueError(f"Unsupported fetch command: {command}")


def _extend_data(args: argparse.Namespace, root: Path) -> int:
    """Make vintage extension explicit and decision-record-backed."""

    from weather_basis.ingest.nclimgrid import Month

    through = Month.parse(args.through)
    decision = args.decision.resolve()
    if not decision.is_file():
        raise FileNotFoundError(f"extension requires a decision record: {decision}")
    text = decision.read_text(encoding="utf-8")
    if "supersedes: D-10" not in text and "supersedes: D-11" not in text:
        raise ValueError("extension decision must supersede D-10 or D-11")
    import yaml

    vintage_path = root / "config/data_vintage.yaml"
    vintage = yaml.safe_load(vintage_path.read_text(encoding="utf-8")) or {}
    for variable in ("nclimgrid_tavg", "nclimgrid_tmax", "nclimgrid_tmin"):
        current = dict(vintage.get(variable) or {})
        current["end"] = str(through)
        current["id"] = f"nclimgrid-daily_v1-0-0_snap{through.year:04d}-{through.month:02d}"
        vintage[variable] = current
    vintage_path.write_text(yaml.safe_dump(vintage, sort_keys=False), encoding="utf-8")
    print(f"extended declared vintage through {through}; fetch and rebuild panels explicitly")
    return 0


def _build_station_panel(root: Path) -> int:
    from weather_basis.ingest.ghcnd import parse_station, qc_station

    cfg = load_config(root / "config/defaults.yaml")
    dates = np.load(root / "data/panel/dates.npy")
    date_index = pd.DatetimeIndex(dates.astype("datetime64[ns]"))
    panel_periods = pd.period_range(date_index.min(), date_index.max(), freq="M")
    panel_months = pd.DataFrame(
        {"year": panel_periods.year.astype(int), "month": panel_periods.month.astype(int)}
    )
    ids = list(cfg.station.ids)
    values = np.full((len(dates), len(ids)), np.nan, dtype=np.float32)
    monthly = []
    for column, station_id in enumerate(ids):
        qc = qc_station(parse_station(root / f"data/raw/ghcnd/{station_id}.csv"), cfg)
        frame = qc.daily.set_index("date").reindex(date_index)
        good = ~frame.qc_status.isin(("excluded", "provisional")) & frame.tbar_f.notna()
        values[good.to_numpy(), column] = frame.loc[good, "tbar_f"].to_numpy(np.float32)
        item = qc.monthly.copy()
        first_period = qc.daily["date"].min().to_period("M")
        item = panel_months.merge(item, on=["year", "month"], how="left", sort=True)
        item_periods = pd.PeriodIndex(
            pd.to_datetime(
                {"year": item["year"], "month": item["month"], "day": np.ones(len(item), int)}
            ),
            freq="M",
        )
        pre_start = item["qc_status"].isna() & (item_periods < first_period)
        item.loc[pre_start, "qc_status"] = "pre_start"
        item.loc[item["qc_status"].isna(), "qc_status"] = "excluded"
        item.insert(0, "ghcnd_id", station_id)
        monthly.append(item)
    write_npy(values, root / "data/panel/stations_tbar_f32.npy")
    write_npy(np.asarray(ids, dtype="U11"), root / "data/panel/station_ids.npy")
    write_parquet(pd.concat(monthly, ignore_index=True), root / "data/panel/station_qc.parquet")
    return 0


def _check_contracts(root: Path) -> int:
    from weather_basis.contracts.universe import load_universe

    universe = load_universe(root / "data/contracts/cme_city_universe.csv")
    calendar = pd.read_csv(root / "data/contracts/cme_contract_calendar.csv")
    strips = pd.read_csv(root / "data/contracts/cme_strips.csv")
    inventory = (root / "data/metadata/ghcnd-stations.txt").read_text(errors="ignore")
    if (len(universe), len(calendar), len(strips)) != (13, 14, 8):
        raise ValueError("contract tables must contain 13 stations, 14 pairs, and 8 strips")
    missing = [station.ghcnd_id for station in universe if station.ghcnd_id not in inventory]
    if missing:
        raise ValueError(f"contract stations absent from GHCN inventory: {missing}")
    return 0


def _build_indices(root: Path, pairs: tuple[Pair, ...]) -> int:
    from weather_basis.indices.county import build_county_frame
    from weather_basis.indices.station import build_station_frame
    from weather_basis.indices.strips import build_strip_frame

    cfg = load_config(root / "config/defaults.yaml")
    dates = np.load(root / "data/panel/dates.npy")
    county = np.load(root / "data/panel/tavg_f32.npy", mmap_mode="r")
    fips = np.load(root / "data/panel/fips.npy")
    station = np.load(root / "data/panel/stations_tbar_f32.npy", mmap_mode="r")
    station_ids = np.load(root / "data/panel/station_ids.npy")
    qc = pd.read_parquet(root / "data/panel/station_qc.parquet")
    county_frames: dict[str, pd.DataFrame] = {}
    station_frames: dict[str, pd.DataFrame] = {}
    for pair in pairs:
        county_frame = build_county_frame(
            county,
            dates,
            fips,
            pair,
            base_f=cfg.contracts.base_f,
            window=cfg.anomaly.window,
            min_prior=cfg.anomaly.min_prior,
        )
        station_frame = build_station_frame(
            station,
            dates,
            station_ids,
            pair,
            station_qc=qc,
            base_f=cfg.contracts.base_f,
            window=cfg.anomaly.window,
            min_prior=cfg.anomaly.min_prior_station,
        )
        write_parquet(county_frame, root / f"results/indices/county_{pair.key}.parquet")
        write_parquet(station_frame, root / f"results/indices/station_{pair.key}.parquet")
        county_frames[pair.key] = county_frame
        station_frames[pair.key] = station_frame
    strips = {
        "HDD-X": (("HDD-11", -1), ("HDD-12", -1), ("HDD-01", 0), ("HDD-02", 0), ("HDD-03", 0)),
        "CDD-K": (("CDD-05", 0), ("CDD-06", 0), ("CDD-07", 0), ("CDD-08", 0), ("CDD-09", 0)),
    }
    for strip, component_keys in strips.items():
        if not all(key in county_frames for key, _ in component_keys):
            continue
        county_strip = build_strip_frame(
            ((county_frames[key], offset) for key, offset in component_keys),
            strip=strip,
            identifier_name="fips",
            window=cfg.anomaly.window,
            min_prior=cfg.anomaly.min_prior,
        )
        station_strip = build_strip_frame(
            ((station_frames[key], offset) for key, offset in component_keys),
            strip=strip,
            identifier_name="ghcnd_id",
            window=cfg.anomaly.window,
            min_prior=cfg.anomaly.min_prior_station,
        )
        write_parquet(county_strip, root / f"results/indices/county_{strip}.parquet")
        write_parquet(station_strip, root / f"results/indices/station_{strip}.parquet")
    return 0


def _atlas_from_indices(root: Path, pairs: tuple[Pair, ...], station_limit: int = 13) -> int:
    from weather_basis.hedge.atlas import PairAtlasInput, run_atlas
    from weather_basis.hedge.bootstrap import year_block_bootstrap
    from weather_basis.hedge.rolling import rolling_residuals
    from weather_basis.hedge.selection import highest_train_corr, nearest, point_in_time_best
    from weather_basis.hedge.zero_distance import station_own_county_table
    from weather_basis.ingest.confidence import haversine_km

    atlas_root = root / "results/atlas"
    tracked_before = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(atlas_root.rglob("*"))
        if path.is_file()
    }
    headline_path = atlas_root / "headline.json"
    if headline_path.is_file():
        tracked_before[headline_path.relative_to(root).as_posix()] = sha256(headline_path)

    cfg = load_config(root / "config/defaults.yaml")
    counties = pd.read_csv(root / "data/metadata/counties.csv", dtype={"fips": str})
    registry = pd.read_csv(root / "data/metadata/station_registry.csv").iloc[:station_limit]
    strip_keys = ("HDD-X", "CDD-K")
    monthly_keys = tuple(pair.key for pair in pairs)
    include_strips = monthly_keys == tuple(pair.key for pair in PAIRS)
    keys = monthly_keys + (strip_keys if include_strips else ())
    children = np.random.SeedSequence(cfg.seed).spawn(len(keys))
    payloads = []
    zero_tables = []
    oos_tables = []
    station_county_path = root / "data/contracts/station_county.csv"
    station_counties: dict[str, str] = {}
    if station_county_path.is_file():
        station_county = pd.read_csv(station_county_path, dtype={"county_fips": str})
        station_counties = {
            str(row.ghcnd_id): str(row.county_fips).zfill(5)
            for row in station_county.itertuples(index=False)
        }
    for pair_position, pair_key in enumerate(keys):
        county_frame = pd.read_parquet(root / f"results/indices/county_{pair_key}.parquet")
        station_frame = pd.read_parquet(root / f"results/indices/station_{pair_key}.parquet")
        seasons = np.sort(county_frame.season.unique())
        fips = np.sort(county_frame.fips.astype(str).str.zfill(5).unique())
        county_lookup = counties.assign(fips=counties.fips.astype(str).str.zfill(5)).set_index(
            "fips"
        )
        county_ordered = county_lookup.loc[fips].reset_index()
        ids = registry.ghcnd_id.astype(str).to_numpy()
        county_anomaly = (
            county_frame.pivot(index="season", columns="fips", values="anomaly")
            .reindex(index=seasons, columns=fips)
            .to_numpy()
        )
        station_anomaly = (
            station_frame.pivot(index="season", columns="ghcnd_id", values="anomaly")
            .reindex(index=seasons, columns=ids)
            .to_numpy()
        )
        first = int(np.searchsorted(seasons, cfg.hedge.first_test))
        starts = registry.get("tmax_start", pd.Series(np.full(len(ids), 1951))).to_numpy()
        minimum = np.where(starts <= 1951, cfg.hedge.min_train, cfg.hedge.min_train_station)
        rolling = rolling_residuals(
            county_anomaly, station_anomaly, first_test=first, min_train=minimum
        )
        exposure = county_anomaly[first:]
        choices = point_in_time_best(
            rolling.resid,
            exposure,
            rolling.train_r2,
            registry.get("first_test_season", pd.Series(np.full(len(ids), 1981))).to_numpy(),
            trailing=cfg.hedge.pit_trailing,
            min_oos=cfg.hedge.pit_min_oos,
            seasons=seasons[first:],
        )
        nearest_station = nearest(
            county_ordered[["lon", "lat"]].to_numpy(), registry[["lon", "lat"]].to_numpy()
        )
        train_choice = highest_train_corr(
            np.sign(rolling.h) * np.sqrt(np.clip(rolling.train_r2, 0, 1))
        )
        rows = np.arange(len(exposure))[:, None]
        columns = np.arange(len(fips))[None, :]
        pit = np.where(
            choices >= 0,
            rolling.resid[rows, columns, np.maximum(choices, 0)],
            np.nan,
        )
        near = rolling.resid[:, np.arange(len(fips)), nearest_station]
        station_test_anomaly = station_anomaly[first:]
        pit_station_anomaly = station_test_anomaly[
            np.arange(len(exposure))[:, None], np.maximum(choices, 0)
        ].astype(float, copy=False)
        pit_station_anomaly[choices < 0] = np.nan
        pit_h = np.where(
            choices >= 0,
            rolling.h[rows, columns, np.maximum(choices, 0)],
            np.nan,
        )
        boot = year_block_bootstrap(
            pit,
            near,
            rolling.resid,
            exposure,
            B=cfg.bootstrap.B,
            seed=children[pair_position],
            level=cfg.bootstrap.level,
            h_pit=pit_h,
            h_station=rolling.h,
        )
        distance = np.empty((len(fips), len(ids)))
        for column, station in registry.reset_index(drop=True).iterrows():
            distance[:, column] = haversine_km(
                county_ordered.lat.to_numpy(),
                county_ordered.lon.to_numpy(),
                np.full(len(fips), station.lat),
                np.full(len(fips), station.lon),
            )
        payloads.append(
            PairAtlasInput(
                pair_key,
                seasons[first:],
                fips,
                ids,
                exposure,
                rolling.resid,
                rolling.h,
                rolling.alpha,
                rolling.train_r2,
                nearest_station,
                choices,
                train_choice,
                boot,
                county_ordered.get("pop2020", pd.Series(np.ones(len(fips)))).to_numpy(),
                county_ordered.get(
                    "confidence", pd.Series(["not_assessed"] * len(fips))
                ).to_numpy(),
                distance,
                registry.get("short_record", pd.Series([False] * len(ids))).to_numpy(),
            )
        )
        if station_counties:
            missing = [station_id for station_id in ids if station_id not in station_counties]
            if missing:
                raise ValueError(f"station_county.csv lacks CME station ids: {missing}")
            own_fips = np.array([station_counties[station_id] for station_id in ids])
            own_index = np.array([np.searchsorted(fips, code) for code in own_fips], dtype=int)
            if not np.array_equal(fips[own_index], own_fips):
                raise ValueError("station_county.csv references a county absent from atlas")
        else:
            # The synthetic fixture intentionally has no geocoder provenance;
            # its station locations coincide with county centroids.
            own_index = nearest(
                registry[["lon", "lat"]].to_numpy(), county_ordered[["lon", "lat"]].to_numpy()
            )
        zero_tables.append(
            station_own_county_table(
                pair_key,
                ids,
                own_index,
                rolling.resid,
                exposure,
                seasons[first:],
                fips=fips,
            )
        )
        if pair_key in monthly_keys:
            pit_station_ids = np.empty(choices.shape, dtype=object)
            pit_station_ids[:] = None
            valid_choices = choices >= 0
            pit_station_ids[valid_choices] = ids[choices[valid_choices]]
            oos_tables.append(
                pd.DataFrame(
                    {
                        "pair": pair_key,
                        "fips": np.tile(fips, len(exposure)),
                        "season": np.repeat(seasons[first:], len(fips)),
                        "a_c": exposure.reshape(-1),
                        "a_j_pit": pit_station_anomaly.reshape(-1),
                        "a_j_nearest": station_test_anomaly[:, nearest_station].reshape(-1),
                        "r_pit": pit.reshape(-1),
                        "r_nearest": near.reshape(-1),
                        "station_pit": pit_station_ids.reshape(-1),
                        "station_nearest": np.tile(ids[nearest_station], len(exposure)),
                    }
                )
            )
    cfg = load_config(root / "config/defaults.yaml")
    primary = [item for item in payloads if item.pair in monthly_keys]
    primary_zero = [item for item in zero_tables if str(item.pair.iloc[0]) in monthly_keys]
    run_atlas(
        primary,
        out_dir=root / "results/atlas",
        zero_distance=pd.concat(primary_zero, ignore_index=True),
        oos=pd.concat(oos_tables, ignore_index=True),
        eligible_min_test=cfg.hedge.eligible_min_test,
        stability_threshold=cfg.bootstrap.stability_threshold,
        hedgeable_he=cfg.hedge.hedgeable_he,
        hedgeable_lb=cfg.hedge.hedgeable_lb,
    )
    strips = [item for item in payloads if item.pair in strip_keys]
    if strips:
        strip_pairs, strip_stations, strip_bootstrap = run_atlas(
            strips,
            eligible_min_test=cfg.hedge.eligible_min_test,
            stability_threshold=cfg.bootstrap.stability_threshold,
            hedgeable_he=cfg.hedge.hedgeable_he,
            hedgeable_lb=cfg.hedge.hedgeable_lb,
        )
        write_parquet(strip_pairs, root / "results/atlas/strips.parquet")
        write_parquet(strip_stations, root / "results/atlas/strip_stations.parquet")
        write_parquet(strip_bootstrap, root / "results/atlas/strip_bootstrap.parquet")
    tracked_after = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(atlas_root.rglob("*"))
        if path.is_file()
    }
    equality = {
        name: tracked_before.get(name) == digest
        for name, digest in tracked_after.items()
        if name in tracked_before
    }
    evidence = {
        "hash_equality": equality,
        "previous_hashes": {name: tracked_before[name] for name in equality},
        "current_hashes": {name: tracked_after[name] for name in equality},
    }
    atomic_write_bytes(
        root / "results/qc/atlas_determinism.json",
        (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode(),
    )
    return 0


def _fixture_reproduce(out: Path) -> int:
    import yaml

    from weather_basis.ingest.panel import build_panel
    from weather_basis.pricing.distribution import SortedSamples
    from weather_basis.pricing.quotes import HedgeSpec, JointDraws, PayoffSpec, loaded_quote
    from weather_basis.validation.fixtures import generate_fixture

    if out.exists():
        shutil.rmtree(out)
    paths = generate_fixture(out / "fixture-source")

    # Keep the fixture data root isolated while using the production loaders,
    # indices, rolling OLS, bootstrap and quote routines unchanged.  The only
    # fixture-specific config values describe the shorter source history and
    # the three deliberately generated station files; all modelling thresholds
    # remain the production defaults.
    config_source = Path(__file__).resolve().parents[2] / "config/defaults.yaml"
    config = yaml.safe_load(config_source.read_text(encoding="utf-8"))
    station_ids = ["USW00094846", "USW00014922", "USW00014739"]
    config["panel"]["start"] = "1951-01-01"
    config["panel"]["end"] = "1996-12-31"
    config["station"]["ids"] = station_ids
    config_path = out / "config/defaults.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
    source_root = Path(__file__).resolve().parents[2]
    shutil.copytree(source_root / "web", out / "web")
    shutil.copytree(source_root / "docs", out / "docs")
    shutil.copytree(source_root / "src/weather_basis/schemas", out / "src/weather_basis/schemas")
    shutil.copytree(paths.raw / "averages", out / "data/raw/nclimgrid_daily/averages")
    shutil.copytree(paths.raw / "ghcnd", out / "data/raw/ghcnd")

    counties = pd.read_csv(paths.counties, dtype={"ncei_code": str, "fips": str})
    # The parser applies 18511 -> 11001 after looking up the state prefix.
    # Add the otherwise absent prefix mapping to this fixture-only dimension;
    # the raw CSV still carries 18511 and therefore exercises the remap.
    counties.loc[counties.fips == "11001", "ncei_code"] = "18001"
    population = pd.read_csv(paths.population, dtype=str)
    population["fips"] = population.STATE.str.zfill(2) + population.COUNTY.str.zfill(3)
    counties = counties.merge(population[["fips", "POPESTIMATE2020"]], on="fips", how="left")
    counties = counties.rename(columns={"POPESTIMATE2020": "pop2020"}).sort_values("fips")
    (out / "data/metadata").mkdir(parents=True, exist_ok=True)
    counties.to_csv(out / "data/metadata/counties.csv", index=False)
    station_counties = {"USW00094846": "17031", "USW00014922": "27053", "USW00014739": "25025"}
    locations = counties.set_index("fips")
    registry = pd.DataFrame(
        [
            {
                "ghcnd_id": station_id,
                "lat": locations.loc[fips, "lat"],
                "lon": locations.loc[fips, "lon"],
                "tmax_start": 1951,
                "first_test_season": 1981,
                "short_record": False,
            }
            for station_id, fips in station_counties.items()
        ]
    )
    registry.to_csv(out / "data/metadata/station_registry.csv", index=False)
    # Keep the production payload contract intact even where the compact
    # fixture deliberately has no historical station-change records.
    pd.DataFrame(columns=["ghcnd_id", "event_date", "event_type"]).to_csv(
        out / "data/metadata/station_events.csv", index=False
    )

    cfg = load_config(config_path)
    build_panel(
        "tavg",
        list(_months((1951, 1), (1996, 12))),
        out / "data/raw/nclimgrid_daily",
        out / "data/panel",
        counties,
    )
    _build_station_panel(out)
    # Keep every contract-month informative in this compact fixture.  Center
    # each synthetic series by its own calendar-month climatology at the
    # degree-day threshold, retaining the generated AR innovations and shared
    # spatial shocks while avoiding constant-zero seasonal indexes.
    dates = pd.DatetimeIndex(np.load(out / "data/panel/dates.npy"))
    for panel_name in ("tavg_f32.npy", "stations_tbar_f32.npy"):
        panel_path = out / "data/panel" / panel_name
        panel_values = np.load(panel_path)
        centered = panel_values.astype(np.float64, copy=True)
        for month in range(1, 13):
            selected = dates.month == month
            centered[selected] = 65.0 + centered[selected] - np.nanmean(centered[selected], axis=0)
        write_npy(centered.astype(np.float32), panel_path)
    _build_indices(out, PAIRS)
    _atlas_from_indices(out, PAIRS, station_limit=len(station_ids))
    _write_headline(out)

    # Use the actual monthly index histories as fixture distribution samples.
    # This is deliberately modest (not a model-simulation substitute), but it
    # drives the production empirical distribution and loaded-premium routines
    # rather than supplying hand-written quote rows.
    quote_rows: list[dict[str, object]] = []
    for pair in PAIRS:
        county_indices = pd.read_parquet(out / f"results/indices/county_{pair.key}.parquet")
        station_indices = pd.read_parquet(out / f"results/indices/station_{pair.key}.parquet")
        atlas = pd.read_parquet(out / "results/atlas/pairs.parquet")
        atlas = atlas.loc[atlas.pair == pair.key].set_index("fips")
        for fips, county_frame in county_indices.groupby("fips", sort=True):
            county_index = county_frame.sort_values("season").set_index("season")
            selected = atlas.loc[str(fips).zfill(5), "station_pit"]
            station_id = str(selected) if pd.notna(selected) else station_ids[0]
            station_index = station_indices.loc[station_indices.ghcnd_id == station_id]
            station_index = station_index.sort_values("season").set_index("season")
            common = county_index.index.intersection(station_index.index)
            county_draws = county_index.loc[common, "index"].to_numpy(dtype=float)
            station_draws = station_index.loc[common, "index"].to_numpy(dtype=float)
            finite = np.isfinite(county_draws) & np.isfinite(station_draws)
            county_draws, station_draws = county_draws[finite], station_draws[finite]
            samples = SortedSamples(county_draws)
            strike = float(samples.quantiles(np.array([0.5]))[0])
            quote = loaded_quote(
                PayoffSpec(strike=strike, multiplier=cfg.contracts.multiplier_usd),
                JointDraws(county_draws, station_draws),
                HedgeSpec(station=station_id),
                cfg,
                lam_model=0.0,
            )
            quote_rows.append(
                {
                    "pair": pair.key,
                    "fips": str(fips).zfill(5),
                    "strike": strike,
                    "mid": float(samples.call(np.array([strike]), cfg.contracts.multiplier_usd)[0]),
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "bid_raw": quote.bid_raw,
                    "residual_load_ask": quote.residual_load_ask,
                    "residual_load_bid": quote.residual_load_bid,
                    "model_load": quote.model_load,
                    "friction": quote.friction,
                    "station": station_id,
                }
            )
    write_parquet(pd.DataFrame(quote_rows), out / "results/quotes/quotes.parquet")
    from weather_basis.manifest_stage import write_stage_manifest
    from weather_basis.site.build import build_site

    write_stage_manifest(
        out,
        cfg,
        stage="atlas",
        outputs=[out / "results/atlas"],
        paths_in=[out / "results/indices"],
        started_at=datetime.now(UTC),
    )
    build_site(out, out / "site", cfg)
    write_stage_manifest(
        out,
        cfg,
        stage="reproduce_fixture",
        outputs=[out / "results/atlas", out / "results/quotes", out / "site"],
        paths_in=[out / "fixture-source", out / "data/panel"],
        extra={"fixture": True, "fresh_clone": False},
        started_at=datetime.now(UTC),
    )
    return 0


_SNAPSHOT_REPRODUCE_COMMANDS = (
    ("data", "verify"),
    ("data", "panel", "--variable", "tavg"),
    ("data", "panel", "--variable", "tmax"),
    ("data", "panel", "--variable", "tmin"),
    ("data", "panel", "--variable", "stations"),
    ("data", "qc"),
    ("contracts", "check"),
    ("indices", "build"),
    ("atlas", "run"),
    ("atlas", "run"),
    ("atlas", "headline"),
    ("models", "fit", "--origins", "1991-2022"),
    ("models", "tournament"),
    ("models", "simulate", "--as-of", "site"),
    ("quotes", "build"),
    ("nebraska", "run"),
    ("site", "build"),
    ("site", "check"),
)


def _snapshot_reproduce(root: Path, snapshot: Path, out: Path) -> int:
    """Rebuild a standalone checkout from a frozen raw-data snapshot.

    The command deliberately refuses an existing destination.  A release
    reproduction must never overwrite a user's checkout or silently reuse
    stale derived panels.  The copied tree supplies the frozen code/config;
    raw inputs are supplied *only* by the snapshot and are re-hashed on
    import before any derived command runs.
    """

    from weather_basis.ingest.migrate import import_snapshot
    from weather_basis.manifest_stage import write_reproduction_manifest

    root, snapshot, out = root.resolve(), snapshot.resolve(), out.resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(snapshot)
    if out.exists():
        raise FileExistsError(f"reproduction destination already exists: {out}")

    headline = json.loads((root / "results/atlas/headline.json").read_text(encoding="utf-8"))
    source_commit = str(headline.get("git_commit", ""))
    if len(source_commit) != 40:
        raise ValueError("headline.json must record the full source commit for reproduction")
    clone = subprocess.run(
        ["git", "clone", "--local", "--no-hardlinks", "--quiet", str(root), str(out)],
        check=False,
    )
    if clone.returncode:
        raise RuntimeError("snapshot reproduction could not create a fresh local clone")
    checkout = subprocess.run(
        ["git", "checkout", "--detach", "--quiet", source_commit], cwd=out, check=False
    )
    if checkout.returncode:
        raise RuntimeError(f"snapshot reproduction source commit is unavailable: {source_commit}")
    shutil.rmtree(out / ".git")
    report = import_snapshot(snapshot, out)
    if not report.ok:
        raise RuntimeError(f"snapshot checksum verification failed: {', '.join(report.drift)}")

    launcher = "from weather_basis.cli import main; raise SystemExit(main())"
    replay_env = os.environ.copy()
    replay_env["WBA_SOURCE_COMMIT"] = source_commit
    replay_env["PYTHONPATH"] = os.pathsep.join(
        [str(out / "src"), replay_env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    for command in _SNAPSHOT_REPRODUCE_COMMANDS:
        command_env = replay_env.copy()
        if command[:2] == ("models", "tournament"):
            command_env["WBA_UNLOCK_HOLDOUT"] = "1"
        else:
            command_env.pop("WBA_UNLOCK_HOLDOUT", None)
        completed = subprocess.run(
            [sys.executable, "-c", launcher, *command],
            cwd=out,
            env=command_env,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(f"snapshot reproduction failed: wba {' '.join(command)}")
    tracked = subprocess.run(
        ["git", "ls-files", "*.parquet"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    cfg = load_config(root / "config/defaults.yaml")
    manifest = write_reproduction_manifest(
        root,
        cfg,
        reference_root=root,
        reproduced_root=out,
        snapshot=snapshot,
        parquet_filenames=tracked,
        source_commit=source_commit,
    )
    evidence = json.loads(manifest.read_text(encoding="utf-8"))["extra"]
    equality = {**evidence["hash_equality"], **evidence["parquet_hash_equality"]}
    if not all(equality.values()):
        raise RuntimeError(f"snapshot reproduction hash mismatch: {equality}")
    print(manifest)
    return 0


def _write_headline(root: Path) -> int:
    from weather_basis.hedge.atlas import headline, write_headline
    from weather_basis.manifest import git_commit

    cfg = load_config(root / "config/defaults.yaml")
    pairs = pd.read_parquet(root / "results/atlas/pairs.parquet")
    stations = pd.read_parquet(root / "results/atlas/stations.parquet")
    zero_path = root / "results/atlas/zero_distance.parquet"
    zero = pd.read_parquet(zero_path) if zero_path.exists() else pd.DataFrame({"pair": []})
    payload = headline(
        pairs,
        zero,
        bootstrap_B=cfg.bootstrap.B,
        seed=cfg.seed,
        config_hash=config_hash(cfg),
        git_commit=git_commit(),
        atlas_run_id=f"atlas-{config_hash(cfg)}",
        thresholds=cfg.hedge.threshold_grid,
        stability_threshold=cfg.bootstrap.stability_threshold,
        stations=stations,
    )
    write_headline(payload, root / "results/atlas/headline.json")
    return 0


def _run_nebraska(root: Path) -> int:
    """Write the registered 18-location basis diagnostic across all 14 pairs."""

    station_county = pd.read_csv(
        root / "data/contracts/station_county.csv", dtype={"county_fips": str}
    )
    station_county["county_fips"] = station_county["county_fips"].str.zfill(5)
    atlas = pd.read_parquet(root / "results/atlas/pairs.parquet")
    atlas["fips"] = atlas["fips"].astype(str).str.zfill(5)
    stations = pd.read_parquet(root / "results/atlas/stations.parquet")
    stations["fips"] = stations["fips"].astype(str).str.zfill(5)
    rows = []
    for location in station_county.itertuples(index=False):
        own = stations.loc[
            (stations["fips"] == location.county_fips) & (stations["station"] == location.ghcnd_id)
        ]
        pair_rows = atlas.loc[atlas["fips"] == location.county_fips]
        merged = pair_rows.merge(
            own[["pair", "he_pooled", "rmse", "n_test"]], on="pair", how="left"
        )
        for row in merged.itertuples(index=False):
            rows.append(
                {
                    "ghcnd_id": location.ghcnd_id,
                    "fips": location.county_fips,
                    "pair": row.pair,
                    "own_station_he": row.he_pooled,
                    "own_station_rmse": row.rmse,
                    "own_station_n_test": row.n_test_y,
                    "pit_station": row.station_pit,
                    "pit_he": row.he_pit,
                    "nearest_station": row.station_nearest,
                    "nearest_he": row.he_nearest,
                }
            )
    output = pd.DataFrame(rows).sort_values(["ghcnd_id", "pair"], kind="stable")
    if len(output) != 18 * len(PAIRS):
        raise ValueError("18-location diagnostic did not cover every contract pair")
    write_parquet(output, root / "results/nebraska/basis.parquet")
    return 0


def _run_site(args: argparse.Namespace, root: Path) -> int:
    from weather_basis.site.build import build_site, check_site
    from weather_basis.site.payloads import build_payloads

    cfg = load_config(root / "config/defaults.yaml")
    if args.site_command == "payloads":
        print(build_payloads(root, args.site_path, cfg))
        return 0
    if args.site_command == "build":
        print(build_site(root, args.site_path, cfg))
        return 0
    if args.site_command == "check":
        errors = check_site(root, args.site_path, cfg)
        print("\n".join(errors))
        return int(bool(errors))
    return subprocess.call(["python3", "-m", "http.server", "8000", "-d", str(args.site_path)])


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path.cwd()
    started_at = datetime.now(UTC)
    if args.command == "data":
        result = _run_data(args, root)
        if result == 0:
            cfg = load_config(root / "config/defaults.yaml")
            _manifest_data_command(args, root, cfg, started_at)
        return result
    if args.command == "contracts":
        result = _check_contracts(root)
        cfg = load_config(root / "config/defaults.yaml")
        _write_stage(
            root,
            cfg,
            "contracts_check",
            [root / "data/contracts"],
            [root / "data/metadata/ghcnd-stations.txt"],
            started_at,
        )
        return result
    if args.command == "indices":
        result = _build_indices(root, _selected_pairs(args.pairs))
        cfg = load_config(root / "config/defaults.yaml")
        _write_stage(
            root, cfg, "indices", [root / "results/indices"], [root / "data/panel"], started_at
        )
        return result
    if args.command == "atlas":
        if args.atlas_command == "run":
            result = _atlas_from_indices(root, _selected_pairs(args.pairs))
            stage = "atlas"
            outputs = [root / "results/atlas", root / "results/qc/atlas_determinism.json"]
        else:
            result = _write_headline(root)
            stage = "atlas_headline"
            outputs = [root / "results/atlas/headline.json"]
        cfg = load_config(root / "config/defaults.yaml")
        _write_stage(
            root,
            cfg,
            stage,
            outputs,
            [root / "results/indices"],
            started_at,
        )
        if args.atlas_command == "headline":
            # Keep the command-specific receipt while refreshing the aggregate
            # atlas manifest consumed by Gate 3 and the site builder.
            _write_stage(
                root,
                cfg,
                "atlas",
                [root / "results/atlas", root / "results/qc/atlas_determinism.json"],
                [root / "results/indices"],
                started_at,
            )
        return result
    if args.command == "site":
        site_root = args.site_path.resolve().parent if args.fixture else root
        result = _run_site(args, site_root)
        if result == 0 and args.site_command in {"payloads", "build", "check"}:
            output = args.site_path.resolve()
            manifest_root = site_root if args.fixture else root
            try:
                output.relative_to(manifest_root.resolve())
            except ValueError:
                pass  # Temporary development builds are outside release provenance.
            else:
                cfg = load_config(manifest_root / "config/defaults.yaml")
                stage = f"site_{args.site_command}"
                outputs = [output]
                if args.site_command == "build" and (manifest_root / "README.md").exists():
                    outputs.append(manifest_root / "README.md")
                _write_stage(
                    manifest_root,
                    cfg,
                    stage,
                    outputs,
                    [manifest_root / "results"],
                    started_at,
                    manifest_path=manifest_root
                    / f"results/manifests/site/{args.site_command}.json",
                )
        return result
    if args.command == "models":
        from weather_basis.models.run import run_tournament
        from weather_basis.models.run_daily import build_mean_blocks, run_site_daily

        cfg = load_config(root / "config/defaults.yaml")
        if args.models_command == "fit":
            try:
                first_origin, last_origin = (int(value) for value in args.origins.split("-", 1))
            except ValueError as exc:
                raise ValueError("--origins must be START-END") from exc
            expected_origins = tuple(int(value) for value in cfg.tournament.origins)
            if (first_origin, last_origin) != expected_origins:
                raise ValueError(
                    f"--origins must equal the registered range "
                    f"{expected_origins[0]}-{expected_origins[1]}"
                )
            build_mean_blocks(root, cfg)
            print(root / "data/panel/mean_blocks.npz")
            _write_stage(
                root,
                cfg,
                "models_fit",
                [root / "data/panel/mean_blocks.npz"],
                [root / "data/panel/tavg_f32.npy"],
                started_at,
            )
            return 0
        if args.models_command == "tournament":
            from weather_basis.manifest_stage import write_sensitivity_manifest
            from weather_basis.models.sensitivity import run_sensitivities
            from weather_basis.validation.atlas_sensitivity import run_atlas_anomaly_sensitivity

            print(run_tournament(root, cfg))
            sensitivity = run_sensitivities(root, cfg)
            atlas_sensitivity = run_atlas_anomaly_sensitivity(root)
            write_sensitivity_manifest(
                root,
                cfg,
                outputs=[sensitivity, atlas_sensitivity],
                inputs=[root / "results/indices", root / "data/panel", root / "data/metadata"],
                started_at=started_at,
            )
            print({"sensitivities": sensitivity, "atlas_anomaly_sensitivities": atlas_sensitivity})
            _write_stage(
                root,
                cfg,
                "tournament",
                [root / "results/tournament", root / "results/models/params"],
                [root / "results/indices", root / "data/panel"],
                started_at,
                holdout_unlocked=os.environ.get("WBA_UNLOCK_HOLDOUT") == "1",
            )
            return 0
        if args.models_command == "simulate":
            if args.as_of != "site":
                raise ValueError("the production simulation accepts only the registered site as-of")
            print(run_site_daily(root, cfg))
            _write_stage(
                root,
                cfg,
                "models_simulate",
                [
                    root / "results/draws/R2j",
                    root / "results/draws/R2j_aligned",
                    root / "results/draws/R2j_aligned_seed2",
                    root / "results/models",
                    root / "results/tournament/calibration.parquet",
                ],
                [root / "data/panel"],
                started_at,
            )
            return 0
    if args.command == "quotes":
        from weather_basis.pricing.run import run_quotes

        cfg = load_config(root / "config/defaults.yaml")
        print(run_quotes(root, cfg))
        _write_stage(
            root,
            cfg,
            "quotes",
            [root / "results/quotes"],
            [root / "results/draws/R2j_aligned", root / "results/atlas"],
            started_at,
        )
        return 0
    if args.command == "nebraska":
        result = _run_nebraska(root)
        cfg = load_config(root / "config/defaults.yaml")
        _write_stage(
            root,
            cfg,
            "nebraska",
            [root / "results/nebraska"],
            [root / "results/atlas", root / "data/contracts/station_county.csv"],
            started_at,
        )
        return result
    if args.command == "reproduce":
        if args.fixture == bool(args.snapshot):
            raise ValueError("choose exactly one of --fixture or --snapshot")
        if args.fixture:
            return _fixture_reproduce(args.out)
        return _snapshot_reproduce(root, args.snapshot, args.out)
    if args.command == "gate":
        completed = subprocess.run(
            ["pytest", "-o", "addopts=", "-m", "data", f"tests/gates/test_phase{args.number}.py"],
            check=False,
        )
        if completed.returncode:
            return completed.returncode
        result_path = root / f"results/gates/gate_{args.number}.json"
        atomic_write_bytes(
            result_path,
            (
                json.dumps(
                    {
                        "gate": int(args.number),
                        "passed": True,
                        "test": f"tests/gates/test_phase{args.number}.py",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode(),
        )
        cfg = load_config(root / "config/defaults.yaml")
        _write_stage(
            root,
            cfg,
            f"gate_{args.number}",
            [result_path],
            [root / f"tests/gates/test_phase{args.number}.py"],
            started_at,
        )
        return 0
    raise SystemExit(f"{args.command} requires generated inputs not yet available")
