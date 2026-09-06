"""Bounded V2 public projections from frozen production artifacts.

This adapter only projects already-produced records.  It deliberately does not
create a national scenario matrix or re-run a weather model while publishing.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_basis.provenance.ids import canonical_json, content_id, file_sha256
from weather_basis.publishing.projections import county_projection, envelope
from weather_basis.schemas.base import require
from weather_basis.schemas.public import ResultEnvelope
from weather_basis.schemas.scenarios import ScenarioMatrix, ScenarioSet


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    return path


def _public_value(value: Any) -> Any:
    """Convert small pricing dataclasses to canonical JSON primitives."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: _public_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_public_value(item) for item in value]
    return value


def _single(paths: list[Path], label: str) -> Path:
    unique = {path.resolve() for path in paths if path.is_file() or path.is_dir()}
    if len(unique) != 1:
        raise FileNotFoundError(f"Expected one {label}; found {len(unique)}")
    return next(iter(unique))


def _scenario_directory(context) -> Path:
    candidates: list[Path] = []
    for parent in context.dependency_directories.get("scenarios.build", []):
        if (parent / "manifest.json").is_file():
            candidates.append(parent)
        candidates.extend(path.parent for path in parent.rglob("manifest.json"))
    valid = []
    for directory in candidates:
        manifest = directory / "manifest.json"
        if not manifest.is_file():
            continue
        record = json.loads(manifest.read_text())
        if record.get("kind") == "r2j-production-stream":
            valid.append(directory)
    return _single(valid, "selected R2j production scenario artifact")


def _matrix(path: Path) -> ScenarioMatrix:
    with np.load(path, allow_pickle=False) as data:
        return ScenarioMatrix(
            parent_scenario_set_id=str(data["parent_scenario_set_id"].item()),
            scenario_ids=tuple(str(x) for x in data["scenario_ids"]),
            entity_ids=tuple(str(x) for x in data["entity_ids"]),
            values=np.asarray(data["values"], dtype=np.float64),
            units=str(data["units"].item()),
        )


def _scenario_inputs(context) -> tuple[Path, dict[str, Any], ScenarioSet]:
    directory = _scenario_directory(context)
    manifest = json.loads((directory / "manifest.json").read_text())
    require(
        manifest.get("status") in {"benchmark", "complete", "candidate-production-artifact"},
        "R2j artifact is not an accepted bounded production result",
    )
    scenario_set = ScenarioSet.from_dict(manifest["scenario_set"])
    require(manifest.get("station_chunk"), "R2j artifact lacks shared station chunk")
    require(manifest.get("county_chunks"), "R2j artifact lacks county chunks")
    if context.request["mode"] == "full":
        require(
            manifest["status"] == "candidate-production-artifact",
            "Full public release requires the registered national R2j artifact",
        )
        require(
            manifest.get("public_paths") == 2000,
            "Full public release requires exactly the frozen 2,000-path public prefix",
        )
        require(
            len(manifest["county_chunks"]) == 3107,
            "Full public release requires all canonical county scenario chunks",
        )
    public_paths = int(manifest.get("public_paths", len(scenario_set.scenario_ids)))
    if len(scenario_set.scenario_ids) > public_paths:
        ids = scenario_set.scenario_ids[:public_paths]
        weights = np.asarray(scenario_set.probability_weights[:public_paths], dtype=float)
        weights /= weights.sum()
        scenario_set = replace(
            scenario_set,
            scenario_set_id=content_id(
                {
                    "parent": scenario_set.scenario_set_id,
                    "paths": public_paths,
                    "rule": manifest["public_slice_rule"],
                }
            ),
            scenario_ids=ids,
            probability_weights=tuple(weights.tolist()),
            scenario_id_hash=content_id(list(ids)),
        )
    return directory, manifest, scenario_set


def _artifact_matrix(directory: Path, filename: str, scenario_set: ScenarioSet) -> ScenarioMatrix:
    matrix = _matrix(directory / filename)
    require(
        matrix.scenario_ids[: len(scenario_set.scenario_ids)] == scenario_set.scenario_ids,
        "Scenario coordinates do not contain the declared public prefix",
    )
    if matrix.parent_scenario_set_id != scenario_set.scenario_set_id:
        matrix = ScenarioMatrix(
            parent_scenario_set_id=scenario_set.scenario_set_id,
            scenario_ids=scenario_set.scenario_ids,
            entity_ids=matrix.entity_ids,
            values=matrix.values[: len(scenario_set.scenario_ids)],
            units=matrix.units,
        )
    require(matrix.units == "degree_days", "Public R2j indexes must be degree days")
    return matrix


def _station_entities(matrix: ScenarioMatrix, pair: str) -> tuple[str, ...]:
    return tuple(entity for entity in matrix.entity_ids if entity.endswith(f":{pair}"))


def _pair_dates(pair: str) -> dict[str, str | int]:
    """Map one monthly matrix coordinate to its actual 2026--27 daily window."""
    index, raw_month = pair.split("-")
    month = int(raw_month)
    year = 2026 if month >= 7 else 2027
    import calendar

    return {
        "pair": pair,
        "index": index,
        "month": month,
        "start": f"{year:04d}-{month:02d}-01",
        "end": f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}",
    }


def _seasonal_structures(pair: str) -> list[dict[str, Any]]:
    """Offer only contiguous subsets represented by the public July--June matrix."""
    definitions = (
        ("hdd-nov26-mar27", ("HDD-11", "HDD-12", "HDD-01", "HDD-02", "HDD-03")),
        ("cdd-jul26-sep26", ("CDD-07", "CDD-08", "CDD-09")),
    )
    result = []
    for name, members in definitions:
        if pair not in members:
            continue
        windows = [_pair_dates(member) for member in members]
        for aggregation, label in (
            ("option_on_strip", "One option on the sum of member monthly indexes"),
            ("sum_of_monthly_options", "Sum of separately evaluated monthly options"),
        ):
            result.append(
                {
                    "structure_id": f"{aggregation}:{name}",
                    "aggregation": aggregation,
                    "label": label,
                    "member_pair_ids": list(members),
                    "member_windows": windows,
                    "matrix_requirement": (
                        "same aligned scenario IDs; use each member entity column"
                    ),
                }
            )
    return result


def _county_registry(root: Path) -> dict[str, dict[str, Any]]:
    frame = pd.read_csv(root / "data/metadata/counties.csv", dtype={"fips": str})
    rows = {
        str(item.fips).zfill(5): {
            "fips": str(item.fips).zfill(5),
            "name": item.name,
            "state": item.state_abbr,
        }
        for item in frame.itertuples(index=False)
    }
    require(len(rows) == 3107, "Expected CONUS 3107 county registry")
    return rows


def _r01_directory(context) -> Path:
    """Resolve R01 from the registered atlas parent, not a mutable legacy alias."""
    candidates: list[Path] = []
    for parent in context.dependency_directories.get("atlas.evaluate", []):
        if (parent / "matched_comparisons.parquet").is_file():
            candidates.append(parent)
        candidates.extend(path.parent for path in parent.rglob("matched_comparisons.parquet"))
        summary = parent / "r01-source.json"
        if summary.is_file():
            source = json.loads(summary.read_text())
            path = Path(source["path"])
            candidates.append(path if path.is_absolute() else context.root / path)
    # The fixed locator exists solely for direct local smoke runs before a
    # planner has registered an atlas parent.
    if not candidates:
        candidates.append(context.root / "results/v2/r01-candidate")
    directory = _single(candidates, "registered corrected R01 output")
    require(
        (directory / "matched_comparisons.parquet").is_file(),
        "R01 candidate lacks matched comparisons",
    )
    require(
        len(pd.read_parquet(directory / "matched_comparisons.parquet")) == 43498,
        "Corrected R01 must contain 43,498 paired county rows",
    )
    return directory


def _context(context, scenario_set: ScenarioSet | None = None) -> dict[str, Any]:
    ids = tuple(str(value) for value in context.input_artifacts.values())
    require(ids, "Public projection requires pinned source artifacts")
    return {
        "release_id": "candidate",
        "analysis_id": context.analysis_id,
        "source_artifact_ids": ids,
        "data_vintage_id": scenario_set.data_vintage_id if scenario_set else "v1-frozen-2026-09-05",
        "model_spec_ids": scenario_set.model_spec_ids if scenario_set else (),
        "scenario_set_id": None if scenario_set is None else scenario_set.scenario_set_id,
        "valuation_asof": context.research["valuation_asof"],
        "evidence_reference": "Pinned V2 production artifacts; see release lock.",
    }


def _county_record(
    *, row: dict[str, Any], registry: dict[str, Any], common: dict[str, Any]
) -> ResultEnvelope:
    """Keep the public boundary strict: projection rows have no silent fields."""
    row = _public_value(row)
    row = dict(row)
    matched = dict(row["matched_policy"])
    for field in ("selection_stability", "coverage", "n_excluded"):
        if field in row:
            matched[field] = row.pop(field)
    row["matched_policy"] = matched
    allowed = {
        "fips",
        "pair",
        "historical_evidence",
        "current_availability",
        "selection_asof",
        "matched_policy",
        "alternatives",
        "distribution",
    }
    required = allowed - {"alternatives", "distribution"}
    require(
        required <= row.keys() and set(row) <= allowed,
        "Unknown or missing county projection fields",
    )
    return county_projection(row=row, registry=registry, context=common)


def _load_quote_selection(context, pair: str) -> dict[str, Any]:
    candidates = [
        directory / f"{pair}.json"
        for directory in context.dependency_directories.get("atlas.select_asof", [])
    ]
    path = _single(candidates, f"atlas.select_asof/{pair}.json")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "Invalid as-of selection")
    return value


def _quotes(context, out: Path) -> list[Path]:
    from weather_basis.pricing.v2 import SelectionAsOfV2, V2Payoff, price_v2

    directory, manifest, scenario_set = _scenario_inputs(context)
    stations = _artifact_matrix(directory, manifest["station_chunk"], scenario_set)
    pairs = tuple(context.request["pairs"]) or tuple(context.research["pairs"])
    requested = tuple(context.request.get("county_panel", ()))
    if not requested:
        requested = (
            tuple(_county_registry(context.root))
            if context.request["mode"] == "full"
            else ("31109",)
        )
    selections_by_pair = {pair: _load_quote_selection(context, pair) for pair in pairs}
    station_by_pair = {pair: (_station_entities(stations, pair), None) for pair in pairs}
    for pair, (station_ids, _) in station_by_pair.items():
        station_by_pair[pair] = (
            station_ids,
            stations.select(station_ids).values if station_ids else None,
        )
    results = []
    # Read each county chunk once.  A pair-major loop would reopen all 3,107
    # compressed chunks fourteen times during a national quote build.
    for fips in requested:
        filename = manifest["county_chunks"].get(fips)
        if filename is None:
            for pair in pairs:
                results.append(
                    {
                        "fips": fips,
                        "pair": pair,
                        "status": "unavailable",
                        "reason_code": "county_scenario_matrix_not_publicly_materialized",
                    }
                )
            continue
        county_matrix = _artifact_matrix(directory, filename, scenario_set)
        for pair in pairs:
            county_entity = f"{fips}:{pair}"
            require(
                county_entity in county_matrix.entity_ids,
                f"Scenario matrix lacks county {county_entity}",
            )
            selection = selections_by_pair[pair].get(fips)
            require(isinstance(selection, dict), f"Missing current selection for {fips}/{pair}")
            station_id = selection.get("station_id")
            station_entity = None if station_id is None else f"{station_id}:{pair}"
            selected_index = (
                -1
                if station_entity not in stations.entity_ids
                else stations.entity_ids.index(station_entity)
            )
            chosen = SelectionAsOfV2(
                valuation_date=date.fromisoformat(selection["valuation_date"]),
                contract_window_id=str(selection.get("contract_window_id", pair)),
                contract_year=int(selection["contract_year"]),
                observation_cutoff=date.fromisoformat(
                    selection.get("observation_cutoff", selection["valuation_date"])
                ),
                metadata_cutoff=date.fromisoformat(
                    selection.get("metadata_cutoff", selection["valuation_date"])[:10]
                ),
                choice_station_index=selected_index,
                selected_station_id=station_entity,
                reason=str(selection.get("reason_code", "unavailable")),
            )
            county = county_matrix.select((county_entity,)).values[:, 0]
            station_ids, station_values = station_by_pair[pair]
            strike = float(np.median(county))
            price = price_v2(
                payoff_spec=V2Payoff("call", strike=strike, multiplier=20.0),
                county_paths=county,
                station_paths=station_values,
                selection_asof=chosen,
                county_scenario_ids=county_matrix.scenario_ids,
                station_scenario_ids=stations.scenario_ids,
                station_entity_ids=station_ids,
            )
            results.append(
                {
                    "fips": fips,
                    "pair": pair,
                    "price": {
                        name: vars(getattr(price, name))
                        for name in (
                            "physical",
                            "unhedged",
                            "hedged",
                            "model_load",
                            "loaded",
                            "market",
                        )
                    },
                    "selection_asof": _public_value(vars(price.selection_asof)),
                    "hedge_ratio": price.hedge_ratio,
                    "option_contract": {
                        "contract_spec_id": "v2-public-physical-option-v1",
                        "payoff": {
                            "kind": "call",
                            "strike": strike,
                            "cap_usd": None,
                            "payout_usd_per_degree_day": 20.0,
                        },
                        "currency": "USD",
                        "underlying": {
                            "entity_id": county_entity,
                            "pair": pair,
                            "units": "degree_days",
                        },
                        "contract_year": chosen.contract_year,
                        "daily_window": _pair_dates(pair),
                        "selection_semantics": (
                            "fresh as-of prior-score choice; "
                            "historical matched evaluation is separate"
                        ),
                        "seasonal_structures": _seasonal_structures(pair),
                    },
                }
            )
    return [
        _write(
            out / "quotes.json",
            {
                "schema_version": "2.0",
                "scenario_set_id": scenario_set.scenario_set_id,
                "quotes": results,
            },
        )
    ]


def _research_records(
    root: Path, common: dict[str, Any], r01_directory: Path | None = None
) -> dict[str, ResultEnvelope]:
    from weather_basis.research.evidence_surfaces import evidence_envelopes
    from weather_basis.research.publishing import research_envelopes

    records = research_envelopes(
        root, release_id=common["release_id"], data_vintage_id=common["data_vintage_id"]
    )
    records.update(
        evidence_envelopes(
            root,
            release_id=common["release_id"],
            data_vintage_id=common["data_vintage_id"],
            valuation_asof=common["valuation_asof"],
        )
    )
    evidence = records["method"]
    common_evidence = {
        "release_id": evidence.release_id,
        "analysis_id": evidence.analysis_id,
        "source_artifact_ids": evidence.source_artifact_ids,
        "data_vintage_id": evidence.data_vintage_id,
        "model_spec_ids": evidence.model_spec_ids,
        "scenario_set_id": None,
        "valuation_asof": evidence.valuation_asof,
        "evidence_reference": evidence.evidence_reference,
    }
    r01_directory = r01_directory or root / "results/v2/r01-candidate"
    r01 = json.loads((r01_directory / "r01_protocol.json").read_text())
    matched_path = r01_directory / "matched_comparisons.parquet"
    matched = pd.read_parquet(matched_path)
    evaluable = matched.reason.eq("ok")
    better = evaluable & (matched.he_prior_best > matched.he_nearest)
    records["nebraska"] = envelope(
        result_type="research",
        payload=records["nebraska"].payload,
        status="partial",
        reason_code="historical_case_predictive_books_published_separately",
        units="degree_days",
        **common_evidence,
    )
    r04 = json.loads((root / "results/v2/experiments/R04-v3-corrected/report.json").read_text())
    records.update(
        {
            "r01": envelope(
                result_type="research_evidence",
                payload={
                    "protocol": r01,
                    "scope": "corrected paired national evaluation",
                    "results": {
                        "county_window_records": len(matched),
                        "evaluable": int(evaluable.sum()),
                        "unavailable": int((~evaluable).sum()),
                        "prior_best_exceeds_nearest": int(better.sum()),
                        "fraction_of_evaluable": float(better.sum() / evaluable.sum()),
                    },
                    "interpretation": (
                        "Prior-score station selection improves on nearest in a minority "
                        "of matched county/window records; no universal improvement is supported."
                    ),
                    "matched_table_sha256": file_sha256(matched_path),
                },
                status="partial",
                reason_code="retrospective_historical_evidence",
                units="degree_days",
                **common_evidence,
            ),
            "r04": envelope(
                result_type="research_evidence",
                payload={"report": r04, "scope": "corrected registered generator evaluation"},
                status="partial",
                reason_code="two_scoreable_origins_inconclusive",
                units="degree_days",
                **common_evidence,
            ),
            "data": envelope(
                result_type="research_evidence",
                payload=records["source_support"].payload,
                status="partial",
                reason_code="frozen_research_vintage_not_settlement_feed",
                units="degree_days",
                **common_evidence,
            ),
            "releases": envelope(
                result_type="research_evidence",
                payload={
                    "schema_version": "2.0",
                    "release_lock": "release-lock.json",
                    "verified_bundle_inventory": "bundle-manifest.json",
                    "source_artifact_ids": list(common["source_artifact_ids"]),
                    "release_policy": "sealed bundle is built only from pinned public projections",
                },
                status="available",
                reason_code=None,
                units="degree_days",
                **common_evidence,
            ),
        }
    )
    return records


def _public_source(context, out: Path) -> None:
    r01 = _r01_directory(context)
    directory, manifest, scenario_set = _scenario_inputs(context)
    # Do this before traversing R01: station paths are mandatory for an
    # available physical hedge indication and cannot be silently downgraded.
    station_matrix = _artifact_matrix(directory, manifest["station_chunk"], scenario_set)
    registry = _county_registry(context.root)
    common = _context(context, scenario_set)
    from weather_basis.hedge.public import build_atlas_public_rows
    from weather_basis.research.evidence_surfaces import scenario_room_envelopes
    from weather_basis.research.publishing import compile_sample_books, evaluate_scenario_room

    station_ids = (
        pd.read_csv(context.root / "data/metadata/station_registry.csv")
        .iloc[:13]
        .ghcnd_id.astype(str)
        .to_numpy()
    )
    rows = build_atlas_public_rows(
        context.root,
        r01,
        modeled_station_ids=station_ids,
        valuation_date=date.fromisoformat(common["valuation_asof"]),
    )
    source_dir = out / "public-records"
    references: dict[str, dict[str, str]] = {}

    def retain(key: str, record: ResultEnvelope) -> None:
        path = source_dir / f"{content_id(key, prefix='public-key').split(':', 1)[1]}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress((canonical_json(record.to_dict()) + "\n").encode(), mtime=0))
        references[key] = {
            "source_path": str(path.relative_to(out)),
            "sha256": file_sha256(path),
        }

    objects: dict[str, ResultEnvelope] = {}
    quote_paths = [
        directory / "quotes.json"
        for directory in context.dependency_directories.get("quotes.build", [])
    ]
    if quote_paths:
        quote_payload = json.loads(_single(quote_paths, "quotes.build/quotes.json").read_text())
        require(
            quote_payload.get("scenario_set_id") == scenario_set.scenario_set_id,
            "Quote scenario set differs from public scenario set",
        )
        for quote in quote_payload.get("quotes", []):
            require("fips" in quote and "pair" in quote, "Invalid public quote record")
            retain(
                f"quote:{quote['fips']}:{quote['pair']}",
                envelope(
                    result_type="contract_ticket",
                    payload=quote,
                    units="USD",
                    currency="USD",
                    **common,
                ),
            )
    summary_rows: dict[str, list[dict[str, Any]]] = {pair: [] for pair in context.research["pairs"]}
    matched_source = pd.read_parquet(r01 / "matched_comparisons.parquet").set_index(
        ["fips", "pair"]
    )
    count = 0
    for row in rows:
        require(row["fips"] in registry, "R01 county absent from canonical registry")
        evidence = matched_source.loc[(row["fips"], row["pair"])]
        rmse = (
            float(
                np.sqrt(
                    max(0.0, (1.0 - evidence.he_prior_best) * evidence.denominator)
                    / evidence.n_common
                )
            )
            if evidence.reason == "ok" and evidence.n_common > 0
            else None
        )
        row["matched_policy"]["residual_rmse_degree_days"] = rmse
        record = _county_record(row=row, registry=registry[row["fips"]], common=common)
        retain(f"county:{row['fips']}:{row['pair']}", record)
        matched = record.payload["matched_policy"]
        summary_rows[row["pair"]].append(
            {
                "fips": row["fips"],
                "layers": {
                    "matched_he": {
                        "value": matched["metric"]["value"],
                        "units": matched["metric"]["units"],
                        "label": "Matched historical hedge effectiveness",
                    },
                    "delta_he": {
                        "value": matched["delta_he"],
                        "units": "ratio",
                        "label": "Prior-best minus nearest matched HE",
                    },
                    "coverage": {
                        "value": matched["n_common"],
                        "units": "seasons",
                        "label": "Matched evaluation seasons",
                    },
                    "interval_width": {
                        "value": (
                            matched["interval"]["high"] - matched["interval"]["low"]
                            if matched["interval"]["high"] is not None
                            and matched["interval"]["low"] is not None
                            else None
                        ),
                        "units": "ratio",
                        "label": "Width of matched-HE improvement interval",
                    },
                    "selection_stability": {
                        "value": matched.get("selection_stability"),
                        "units": "fraction",
                        "label": "Historical station-selection stability",
                    },
                    "current_proxy": {
                        "value": record.payload["selection_asof"].get("station_name"),
                        "units": "category",
                        "label": "Current as-of selected research proxy",
                    },
                    "residual_risk": {
                        "value": rmse,
                        "units": "degree_days",
                        "label": "Matched historical residual RMSE; larger is worse",
                    },
                    "current_availability": {
                        "value": record.payload["current_availability"]["status"],
                        "units": "category",
                        "label": "Current scenario availability",
                    },
                },
            }
        )
        count += 1
    require(count == 43498, "Corrected R01 must supply 43,498 county/pair rows")
    for pair in context.research["pairs"]:
        objects[f"summary:{pair}"] = envelope(
            result_type="national_summary",
            payload={"pair": pair, "rows": summary_rows[pair]},
            **common,
        )
    for fips, filename in manifest["county_chunks"].items():
        retain(
            f"county_scenarios:{fips}",
            envelope(
                result_type="scenario_matrix",
                payload={
                    "scenario_set": scenario_set.to_dict(),
                    "matrix": _artifact_matrix(directory, filename, scenario_set).to_dict(),
                },
                **common,
            ),
        )
    objects["station_scenarios"] = envelope(
        result_type="scenario_matrix",
        payload={
            "scenario_set": scenario_set.to_dict(),
            "matrix": station_matrix.to_dict(),
        },
        **common,
    )
    # Books are inexpensive sparse decisions over the frozen paths.  Recompile
    # them here so a changed book or cost policy cannot reuse stale positions.
    compiled = compile_sample_books(
        context.root, directory, out / "books", paths=len(scenario_set.scenario_ids)
    )
    for book_id, result in compiled.items():
        require(
            result["scenario_set_id"] == scenario_set.scenario_set_id,
            "Book result must use the public scenario prefix",
        )
        objects[f"book:{book_id}"] = envelope(
            result_type="book", payload=result, units="USD", currency="USD", **common
        )
    objects.update(
        {
            f"research:{key}": value
            for key, value in _research_records(context.root, common, r01).items()
        }
    )
    rooms = scenario_room_envelopes(
        context.root,
        release_id=common["release_id"],
        data_vintage_id=common["data_vintage_id"],
        valuation_asof=common["valuation_asof"],
    )
    objects.update({f"scenario_room:{key}": value for key, value in rooms.items()})
    for room_key, room in rooms.items():
        for book_id, result in compiled.items():
            cashflows = evaluate_scenario_room(result, room.to_dict())
            objects[f"scenario_room_cashflows:{room_key}:{book_id}"] = envelope(
                result_type="scenario_room_cashflows",
                payload=cashflows,
                release_id=common["release_id"],
                analysis_id=content_id(
                    {"book_result_id": result["result_id"], "room": room.object_id}
                ),
                source_artifact_ids=room.source_artifact_ids
                + (content_id({"book_result_id": result["result_id"]}),),
                data_vintage_id=room.data_vintage_id,
                model_spec_ids=room.model_spec_ids,
                scenario_set_id=room.scenario_set_id,
                valuation_asof=room.valuation_asof,
                index_definition_id=room.index_definition_id,
                units="USD",
                currency="USD",
                evidence_reference=(
                    "Frozen book positions reevaluated on the identified Scenario Room matrix; "
                    "no optimization, pricing, or simulation."
                ),
            )
    default_matrix = _artifact_matrix(directory, manifest["county_chunks"]["31109"], scenario_set)
    strike = float(
        np.median(default_matrix.values[:, default_matrix.entity_ids.index("31109:HDD-01")])
    )
    bootstrap = {
        "schema_version": "2.0",
        "release_id": common["release_id"],
        "route_map": {},
        "county_registry": list(registry.values()),
        "index_definitions": [
            {"id": pair, "units": "degree_days"} for pair in context.research["pairs"]
        ],
        "defaults": {
            "fips": "31109",
            "index_id": "HDD-01",
            "valuation_asof": common["valuation_asof"],
            "contract_window": {"start": "2027-01-01", "end": "2027-01-31", "year": 2027},
            "payoff": {"family": "call", "strike": strike, "multiplier": 20.0},
        },
        "objects": {},
        "scenario_sets": [scenario_set.to_dict()],
        "capabilities": {
            "max_locations": 6,
            "max_exposure_rows": 24,
            "max_hedge_columns": 39,
            "max_horizon_months": 12,
            "public_paths": len(scenario_set.scenario_ids),
            "scope": manifest["status"],
        },
    }
    for key, record in objects.items():
        retain(key, record)
    _write(out / "public-source.json", {"bootstrap": bootstrap, "objects": references})


def handle_real_publishing(stage, context, out):
    """Dispatch production public stages from pinned artifacts only."""
    if stage == "atlas.select_asof":
        raise ValueError(
            "atlas.select_asof is projected by the hedge adapter before public release"
        )
    if stage == "quotes.build":
        return _quotes(context, out)
    if stage == "cases.build":
        _public_source(context, out)
        return None
    if stage == "site.build":
        from weather_basis.application.publishing import make_release_lock
        from weather_basis.publishing.release import build_release

        source = _single(
            [path / "public-source.json" for path in context.dependency_directories["cases.build"]],
            "cases public source",
        )
        lock = make_release_lock(
            context.root,
            source,
            scope="national_production"
            if context.request["mode"] == "full"
            else "bounded_production",
            artifacts=[
                {
                    "artifact_id": content_id({"source": str(source.relative_to(context.root))}),
                    "path": str(source.relative_to(context.root)),
                    "sha256": file_sha256(source),
                    "access_class": "public_release",
                }
            ],
        )
        lock_path = _write(out / "release.lock.json", lock)
        build_release(context.root, lock_path, out / "bundle")
        return None
    if stage == "release.verify":
        from weather_basis.publishing.release import verify_release

        bundle = _single(
            [path / "bundle" for path in context.dependency_directories["site.build"]],
            "site bundle",
        )
        return [_write(out / "verification.json", verify_release(bundle))]
    raise ValueError(f"Unsupported public publishing stage: {stage}")
