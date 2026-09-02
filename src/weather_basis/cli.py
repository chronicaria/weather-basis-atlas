"""Command-line orchestration for Weather Basis Atlas."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.config import config_hash, load_config
from weather_basis.contracts.calendar import PAIRS, Pair
from weather_basis.io import write_npy, write_parquet


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
        report = verify_manifest(
            root / "data/manifests/nclimgrid_tavg.csv", root / "data/raw/nclimgrid_daily"
        )
        print(report)
        return 0 if report.ok else 1
    if args.data_command == "snapshot":
        report = (
            export_snapshot(root, args.out)
            if args.snapshot_command == "export"
            else import_snapshot(args.source, root)
        )
        print(report)
        return 0
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
    values = np.load(root / "data/panel/tavg_f32.npy", mmap_mode="r")
    report = {
        "shape": list(values.shape),
        "nan_count": int(np.isnan(values).sum()),
        "minimum_f": float(np.nanmin(values)),
        "maximum_f": float(np.nanmax(values)),
    }
    target = root / "results/qc/panel_tavg.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    (root / "results/qc/data_through.json").write_text('{"data_through":"2026-06-30"}\n')
    return 0


def _build_station_panel(root: Path) -> int:
    from weather_basis.ingest.ghcnd import parse_station, qc_station

    cfg = load_config(root / "config/defaults.yaml")
    dates = np.load(root / "data/panel/dates.npy")
    date_index = pd.DatetimeIndex(dates.astype("datetime64[ns]"))
    ids = list(cfg.station.ids)
    values = np.full((len(dates), len(ids)), np.nan, dtype=np.float32)
    monthly = []
    for column, station_id in enumerate(ids):
        qc = qc_station(parse_station(root / f"data/raw/ghcnd/{station_id}.csv"), cfg)
        frame = qc.daily.set_index("date").reindex(date_index)
        good = ~frame.qc_status.isin(("excluded", "provisional")) & frame.tbar_f.notna()
        values[good.to_numpy(), column] = frame.loc[good, "tbar_f"].to_numpy(np.float32)
        item = qc.monthly.copy()
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
    assert len(universe) == 13 and len(calendar) == 14 and len(strips) == 8
    assert all(station.ghcnd_id in inventory for station in universe)
    return 0


def _build_indices(root: Path, pairs: tuple[Pair, ...]) -> int:
    from weather_basis.indices.county import build_county_frame
    from weather_basis.indices.station import build_station_frame

    cfg = load_config(root / "config/defaults.yaml")
    dates = np.load(root / "data/panel/dates.npy")
    county = np.load(root / "data/panel/tavg_f32.npy", mmap_mode="r")
    fips = np.load(root / "data/panel/fips.npy")
    station = np.load(root / "data/panel/stations_tbar_f32.npy", mmap_mode="r")
    station_ids = np.load(root / "data/panel/station_ids.npy")
    qc = pd.read_parquet(root / "data/panel/station_qc.parquet")
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
    return 0


def _atlas_from_indices(root: Path, pairs: tuple[Pair, ...], station_limit: int = 13) -> int:
    from weather_basis.hedge.atlas import PairAtlasInput, run_atlas
    from weather_basis.hedge.bootstrap import year_block_bootstrap
    from weather_basis.hedge.rolling import rolling_residuals
    from weather_basis.hedge.selection import nearest, point_in_time_best
    from weather_basis.ingest.confidence import haversine_km

    cfg = load_config(root / "config/defaults.yaml")
    counties = pd.read_csv(root / "data/metadata/counties.csv", dtype={"fips": str})
    registry = pd.read_csv(root / "data/metadata/station_registry.csv").iloc[:station_limit]
    children = np.random.SeedSequence(cfg.seed).spawn(len(PAIRS))
    payloads = []
    for pair in pairs:
        county_frame = pd.read_parquet(root / f"results/indices/county_{pair.key}.parquet")
        station_frame = pd.read_parquet(root / f"results/indices/station_{pair.key}.parquet")
        seasons = np.sort(county_frame.season.unique())
        fips = np.sort(county_frame.fips.astype(str).str.zfill(5).unique())
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
        )
        nearest_station = nearest(
            counties[["lon", "lat"]].to_numpy(), registry[["lon", "lat"]].to_numpy()
        )
        rows = np.arange(len(exposure))[:, None]
        columns = np.arange(len(fips))[None, :]
        pit = np.where(
            choices >= 0,
            rolling.resid[rows, columns, np.maximum(choices, 0)],
            np.nan,
        )
        near = rolling.resid[:, np.arange(len(fips)), nearest_station]
        boot = year_block_bootstrap(
            pit,
            near,
            rolling.resid,
            exposure,
            B=cfg.bootstrap.B,
            seed=children[list(PAIRS).index(pair)],
            level=cfg.bootstrap.level,
        )
        distance = np.empty((len(fips), len(ids)))
        for column, station in registry.reset_index(drop=True).iterrows():
            distance[:, column] = haversine_km(
                counties.lat.to_numpy(),
                counties.lon.to_numpy(),
                np.full(len(fips), station.lat),
                np.full(len(fips), station.lon),
            )
        payloads.append(
            PairAtlasInput(
                pair.key,
                seasons[first:],
                fips,
                ids,
                exposure,
                rolling.resid,
                rolling.h,
                np.sign(rolling.h) * np.sqrt(np.clip(rolling.train_r2, 0, 1)),
                nearest_station,
                choices,
                boot,
                counties.get("pop2020", pd.Series(np.ones(len(fips)))).to_numpy(),
                counties.get("confidence", pd.Series(["not_assessed"] * len(fips))).to_numpy(),
                distance,
                registry.get("short_record", pd.Series([False] * len(ids))).to_numpy(),
            )
        )
    cfg = load_config(root / "config/defaults.yaml")
    run_atlas(
        payloads,
        out_dir=root / "results/atlas",
        eligible_min_test=cfg.hedge.eligible_min_test,
        stability_threshold=cfg.bootstrap.stability_threshold,
        hedgeable_he=cfg.hedge.hedgeable_he,
        hedgeable_lb=cfg.hedge.hedgeable_lb,
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
    focal = {row["pair"]: row for row in payload["pairs"]}
    hdd = 1.0 - float(focal["HDD-01"]["no_hedge_share_counties"])
    cdd = 1.0 - float(focal["CDD-07"]["no_hedge_share_counties"])
    readme = root / "README.md"
    if not readme.exists():
        return 0
    text = readme.read_text(encoding="utf-8")
    start, end = "<!-- atlas-headline:start -->", "<!-- atlas-headline:end -->"
    rendered = (
        f"{start}\nWeather Basis Atlas finds that {hdd:.1%} of counties meet the "
        f"pre-registered January HDD hedgeability rule and {cdd:.1%} meet it "
        f"for July CDD.\n{end}"
    )
    before, separator, remainder = text.partition(start)
    if not separator or end not in remainder:
        raise ValueError("README atlas headline markers are missing")
    _, _, after = remainder.partition(end)
    readme.write_text(before + rendered + after, encoding="utf-8")
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
        if result == 0 and args.data_command in {"migrate", "panel", "qc"}:
            cfg = load_config(root / "config/defaults.yaml")
            if args.data_command == "migrate":
                _write_stage(
                    root,
                    cfg,
                    "data_migrate",
                    [root / "data/manifests/nclimgrid_tavg.csv"],
                    [args.donor],
                    started_at,
                )
            elif args.data_command == "panel":
                _write_stage(
                    root,
                    cfg,
                    "data_panel",
                    [root / "data/panel"],
                    [root / "data/raw", root / "data/metadata"],
                    started_at,
                )
            else:
                _write_stage(
                    root, cfg, "data_qc", [root / "results/qc"], [root / "data/panel"], started_at
                )
        return result
    if args.command == "contracts":
        return _check_contracts(root)
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
        else:
            result = _write_headline(root)
        cfg = load_config(root / "config/defaults.yaml")
        _write_stage(
            root, cfg, "atlas", [root / "results/atlas"], [root / "results/indices"], started_at
        )
        return result
    if args.command == "site":
        result = _run_site(args, root)
        if result == 0 and args.site_command in {"payloads", "build", "check"}:
            output = args.site_path.resolve()
            try:
                output.relative_to(root.resolve())
            except ValueError:
                pass  # Temporary development builds are outside release provenance.
            else:
                cfg = load_config(root / "config/defaults.yaml")
                stage = f"site_{args.site_command}"
                _write_stage(
                    root,
                    cfg,
                    stage,
                    [output],
                    [root / "results"],
                    started_at,
                    manifest_path=root / f"results/manifests/site/{args.site_command}.json",
                )
        return result
    if args.command == "models":
        from weather_basis.models.run import run_tournament
        from weather_basis.models.run_daily import build_mean_blocks, run_site_daily

        cfg = load_config(root / "config/defaults.yaml")
        if args.models_command == "fit":
            print(build_mean_blocks(root, cfg))
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
            print(run_tournament(root, cfg))
            _write_stage(
                root,
                cfg,
                "tournament",
                [root / "results/tournament"],
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
                    root / "results/models",
                    root / "results/tournament/calibration.parquet",
                    root / "results/tournament/joint_check.parquet",
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
    if args.command == "reproduce" and args.fixture:
        return _fixture_reproduce(args.out)
    if args.command == "gate":
        return subprocess.run(
            ["pytest", "-o", "addopts=", "-m", "data", f"tests/gates/test_phase{args.number}.py"],
            check=False,
        ).returncode
    raise SystemExit(f"{args.command} requires generated inputs not yet available")
