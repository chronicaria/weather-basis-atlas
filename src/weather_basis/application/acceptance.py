"""Executed national acceptance checks against identified candidate artifacts.

The candidate file contains locators, never hand-written pass flags. Numerical
and release checks below produce their own results; browser evidence retains
its independently recorded release and scope.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.contracts.calendar import PAIRS
from weather_basis.portfolio.optimize import _constraint_residuals
from weather_basis.portfolio.risk import expected_shortfall
from weather_basis.provenance.ids import content_id, file_sha256
from weather_basis.research.publishing import _compile_problem, _scenario_matrix, loss_on_matrix
from weather_basis.schemas.base import require
from weather_basis.schemas.public import ResultEnvelope
from weather_basis.schemas.scenarios import ScenarioSet


def _path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _json(path: Path):
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return json.loads(raw)


def _r01(root: Path, directory: Path) -> dict:
    frame = pd.read_parquet(directory / "matched_comparisons.parquet")
    expected = {
        (fips, pair.key)
        for fips in np.load(root / "data/panel/fips.npy").astype(str)
        for pair in PAIRS
    }
    actual = set(zip(frame.fips, frame.pair, strict=True))
    require(len(frame) == 43498 and actual == expected, "National atlas coverage is incomplete")
    intervals = pd.read_parquet(directory / "r01_uncertainty_stability.parquet")
    require(
        set(zip(intervals.fips, intervals.pair, strict=True)) == expected,
        "National uncertainty/stability coverage is incomplete",
    )
    ok = frame.reason.eq("ok")
    require(
        np.isfinite(frame.loc[ok, ["he_prior_best", "he_nearest", "denominator"]]).all().all(),
        "Available policy records contain non-finite statistics",
    )
    require((frame.loc[ok, "denominator"] > 0).all(), "Available HE denominator is degenerate")
    require(
        all(not len(years) or max(years) <= 2025 for years in frame.season_ids),
        "Historical evaluation includes a post-2025 season",
    )
    # This expression is independent of the policy evaluator and catches the
    # previously mislabeled direction of the exported paired-loss difference.
    expected_loss = (frame.he_nearest - frame.he_prior_best) * frame.denominator
    require(
        np.allclose(
            frame.loc[ok, "paired_loss_change_prior_minus_nearest"],
            expected_loss[ok],
            rtol=1e-10,
            atol=1e-7,
        ),
        "Paired loss sign mismatch",
    )
    samples = []
    for fips, pair in (
        ("31055", "HDD-01"),
        ("31109", "CDD-07"),
        ("06037", "CDD-06"),
        ("36061", "HDD-01"),
        ("17031", "CDD-06"),
        ("01001", "CDD-04"),
    ):
        row = frame.loc[frame.fips.eq(fips) & frame.pair.eq(pair)].iloc[0]
        evaluation = pd.read_parquet(directory / "policy_evaluations" / f"{pair}.parquet")
        wide = evaluation.loc[evaluation.fips.eq(fips)].pivot(
            index="season", columns="policy", values="residual"
        )
        years = [int(year) for year in row.season_ids]
        indexes = pd.read_parquet(root / "results/indices" / f"county_{pair}.parquet")
        target = indexes.loc[indexes.fips.astype(str).str.zfill(5).eq(fips)].set_index("season")
        values = target.loc[years, "anomaly"].to_numpy(float)
        denominator = float(sum((values - sum(values) / len(values)) ** 2)) if years else 0.0
        if row.reason == "ok":
            require(np.isclose(denominator, row.denominator), "Independent HE denominator differs")
            for name, column in (
                ("prior_best", "he_prior_best"),
                ("nearest_eligible", "he_nearest"),
            ):
                residual = wide.loc[years, name].to_numpy(float)
                he = 1.0 - sum(float(value) ** 2 for value in residual) / denominator
                require(np.isclose(he, row[column]), "Independent matched HE differs")
        samples.append(
            {
                "fips": fips,
                "pair": pair,
                "common_seasons": years,
                "denominator": denominator,
                "reason": row.reason,
            }
        )
    return {
        "rows": len(frame),
        "evaluated": int(ok.sum()),
        "unavailable": int((~ok).sum()),
        "prior_best_beats_nearest": int((ok & (frame.he_prior_best > frame.he_nearest)).sum()),
        "independent_samples": samples,
        "sha256": file_sha256(directory / "matched_comparisons.parquet"),
    }


def _scenarios(root: Path, directory: Path) -> dict:
    manifest = _json(directory / "manifest.json")
    scenario = ScenarioSet.from_dict(manifest["scenario_set"])
    require(manifest["kind"] == "r2j-production-stream", "Unknown national scenario artifact")
    require(
        manifest["observation_cutoff"] == "2026-05-31" and manifest["bridge_days"] == 30,
        "Missing common information cutoff/process bridge",
    )
    require(len(scenario.scenario_ids) == 10000, "Offline adjudication requires 10,000 paths")
    counties = set(np.load(root / "data/panel/fips.npy").astype(str))
    require(set(manifest["county_chunks"]) == counties, "Scenario county coverage is incomplete")
    coordinates = np.asarray(scenario.scenario_ids)
    total_values = 0
    for fips, filename in [
        ("station", manifest["station_chunk"]),
        *sorted(manifest["county_chunks"].items()),
    ]:
        with np.load(directory / filename, allow_pickle=False) as chunk:
            values = chunk["values"]
            require(
                values.shape == (10000, 252 if fips == "station" else 14),
                "Scenario chunk dimensions differ from declared scope",
            )
            require(
                np.array_equal(chunk["scenario_ids"], coordinates), "Scenario coordinate mismatch"
            )
            require(
                str(chunk["parent_scenario_set_id"].item()) == scenario.scenario_set_id,
                "Scenario parent mismatch",
            )
            require(str(chunk["units"].item()) == "degree_days", "Scenario units mismatch")
            require(
                np.isfinite(values).all() and (values >= 0).all(), "Invalid degree-day scenarios"
            )
            total_values += values.size
    # Daily path accumulation is checked outside the streaming reducer.
    max_reconciliation_error = 0.0
    max_rounding_bound = 0.0
    with np.load(directory / manifest["audit_daily_paths"], allow_pickle=False) as audit:
        dates = pd.to_datetime(audit["dates"])
        audit_values = audit["values"]
        within = (dates >= scenario.date_start) & (dates <= scenario.date_end)
        for j, fips in enumerate(audit["location_ids"].astype(str)):
            with np.load(
                directory / manifest["county_chunks"][fips], allow_pickle=False
            ) as monthly:
                monthly_values = monthly["values"]
                for pair in PAIRS:
                    mask = within & (dates.month == pair.month)
                    stored_temperatures = audit_values[:, mask, j]
                    temperatures = stored_temperatures.astype(np.float64)
                    daily = (
                        np.maximum(65.0 - temperatures, 0)
                        if pair.index == "HDD"
                        else np.maximum(temperatures - 65.0, 0)
                    )
                    index = list(monthly["entity_ids"].astype(str)).index(f"{fips}:{pair.key}")
                    stored_total = monthly_values[: daily.shape[0], index]
                    difference = np.abs(daily.sum(axis=1) - stored_total.astype(np.float64))
                    # Both the audit temperatures and monthly totals are stored
                    # as float32. The DD map is 1-Lipschitz, so one half-ULP
                    # per daily input plus one half-ULP of the monthly output
                    # bounds this deliberately quantized reconciliation.
                    rounding_bound = (
                        np.spacing(np.abs(stored_temperatures)).astype(np.float64).sum(axis=1) / 2
                        + np.spacing(np.abs(stored_total)).astype(np.float64) / 2
                        + 8 * np.finfo(float).eps * np.maximum(1, np.abs(temperatures).sum(axis=1))
                    )
                    max_reconciliation_error = max(
                        max_reconciliation_error, float(difference.max())
                    )
                    max_rounding_bound = max(max_rounding_bound, float(rounding_bound.max()))
                    require(
                        bool(np.all(difference <= rounding_bound)),
                        "Daily/monthly reconciliation failed",
                    )
    return {
        "scenario_set_id": scenario.scenario_set_id,
        "counties": len(counties),
        "station_count": 18,
        "paths": 10000,
        "checked_values": total_values,
        "observation_cutoff": manifest["observation_cutoff"],
        "bridge_days": 30,
        "storage_dtype": "float32",
        "canonical_dtype": "float64 promotion",
        "maximum_daily_monthly_error_degree_days": max_reconciliation_error,
        "maximum_analytical_rounding_bound_degree_days": max_rounding_bound,
        "manifest_sha256": file_sha256(directory / "manifest.json"),
    }


def _public(root: Path, source: Path, scenario_directory: Path) -> dict:
    blueprint = _json(source)
    objects = blueprint["objects"]
    require(
        blueprint["bootstrap"]["capabilities"]["public_paths"] == 2000,
        "Public interactive paths must be the fixed 2,000-prefix sample",
    )
    county_count = matrix_count = quote_count = 0
    quote_keys = set()
    books = []
    manifest = _json(scenario_directory / "manifest.json")
    for key, ref in objects.items():
        path = source.parent / ref["source_path"]
        require(file_sha256(path) == ref["sha256"], "Public source record hash mismatch")
        record = ResultEnvelope.from_dict(_json(path))
        if key.startswith("county:"):
            county_count += 1
            require(
                record.payload["county"]["fips"] == key.split(":")[1], "County identity mismatch"
            )
        elif key.startswith("county_scenarios:") or key == "station_scenarios":
            matrix_count += 1
            matrix = record.payload["matrix"]
            fips = key.split(":")[1] if ":" in key else None
            filename = manifest["county_chunks"][fips] if fips else manifest["station_chunk"]
            with np.load(scenario_directory / filename, allow_pickle=False) as offline:
                require(
                    np.array_equal(np.asarray(matrix["values"]), offline["values"][:2000]),
                    "Public scenario values are not the offline prefix",
                )
                require(
                    matrix["scenario_ids"] == offline["scenario_ids"][:2000].tolist(),
                    "Public scenario IDs are not the offline prefix",
                )
        elif key.startswith("book:"):
            book = record.payload
            require(book.get("status") == "available", "Required sample book is unavailable")
            require(
                book.get("scenario_count") == 2000, "Sample book uses a different public sample"
            )
            require(
                book["optimized"]["status"] == "optimal", "Sample book optimizer did not finish"
            )
            books.append(key)
        elif key.startswith("quote:"):
            quote_count += 1
            ticket = record.payload
            identity = (str(ticket["fips"]), ticket["pair"])
            require(identity not in quote_keys, "Duplicate public quote identity")
            quote_keys.add(identity)
    require(county_count == 43498 and matrix_count == 3108, "National public coverage incomplete")
    require(len(books) == 3, "Three executable public sample books are required")
    expected_quotes = {
        (fips, pair.key)
        for fips in np.load(root / "data/panel/fips.npy").astype(str)
        for pair in PAIRS
    }
    require(
        quote_count == len(expected_quotes) and quote_keys == expected_quotes,
        "Public quote coverage incomplete",
    )
    return {
        "county_records": county_count,
        "scenario_matrices": matrix_count,
        "books": books,
        "quote_records": quote_count,
        "source_sha256": file_sha256(source),
    }


def _quotes(root: Path, directory: Path, asof_directory: Path, scenario_directory: Path) -> dict:
    """Validate every public ticket against the frozen as-of selection tape."""
    payload = _json(directory / "quotes.json")
    quotes = payload["quotes"]
    expected_fips = set(np.load(root / "data/panel/fips.npy").astype(str))
    expected = {(fips, pair.key) for fips in expected_fips for pair in PAIRS}
    actual = {(str(row["fips"]), row["pair"]) for row in quotes}
    require(
        len(quotes) == len(expected) and actual == expected, "Public quote coverage is incomplete"
    )
    require(payload.get("scenario_set_id"), "Quotes lack a scenario-set identity")
    manifest = _json(scenario_directory / "manifest.json")
    parent_id = manifest["scenario_set"]["scenario_set_id"]
    expected_scenario_id = content_id(
        {"parent": parent_id, "paths": 2000, "rule": manifest["public_slice_rule"]}
    )
    require(
        payload["scenario_set_id"] == expected_scenario_id, "Quotes use the wrong public prefix"
    )
    with np.load(scenario_directory / manifest["station_chunk"], allow_pickle=False) as station:
        station_ids = set(station["entity_ids"].astype(str))
        require(
            np.array_equal(
                station["scenario_ids"][:2000],
                np.asarray(manifest["scenario_set"]["scenario_ids"][:2000]),
            ),
            "Station scenario coordinates differ from the registered prefix",
        )

    asof = {pair.key: _json(asof_directory / f"{pair.key}.json") for pair in PAIRS}
    checked_available_hedges = 0
    for quote in quotes:
        fips, pair = str(quote["fips"]), quote["pair"]
        selection, source_selection = quote["selection_asof"], asof[pair][fips]
        observation_cutoff = source_selection.get(
            "observation_cutoff", source_selection["valuation_date"]
        )
        metadata_cutoff = source_selection.get(
            "metadata_cutoff", source_selection["valuation_date"]
        ).split(" ")[0]
        require(
            selection["contract_window_id"] == source_selection["contract_window_id"]
            and selection["contract_year"] == source_selection["contract_year"]
            and selection["valuation_date"] == source_selection["valuation_date"]
            and selection["observation_cutoff"] == observation_cutoff
            and selection["metadata_cutoff"] == metadata_cutoff
            and selection["reason"] == source_selection["reason_code"],
            "Quote selection does not match its frozen as-of record",
        )
        station_id = source_selection.get("station_id")
        if station_id:
            require(
                selection["selected_station_id"] == f"{station_id}:{pair}",
                "Quote station identity does not match the frozen selection",
            )
            require(
                selection["selected_station_id"] in station_ids,
                "Selected station is absent from canonical matrix",
            )
        else:
            require(selection["selected_station_id"] is None, "Unavailable selection has a station")
        prices = quote["price"]
        for name, method in (
            ("physical", "common_aligned_paths"),
            ("unhedged", "physical_no_station_hedge"),
        ):
            component = prices[name]
            require(
                component["status"] == "available"
                and component["currency"] == "USD"
                and component["method"] == method
                and np.isfinite(component["amount"]),
                f"{name} quote is not a finite physical indication",
            )
        hedged = prices["hedged"]
        if hedged["status"] == "available":
            require(
                hedged["method"] == "payoff_specific_aligned_station_hedge"
                and np.isfinite(hedged["amount"]),
                "Available hedge quote is invalid",
            )
            checked_available_hedges += 1
        else:
            require(
                hedged["status"] == "unavailable" and hedged["amount"] is None,
                "Unavailable hedge quote has a value",
            )
        for name in ("model_load", "loaded", "market"):
            component = prices[name]
            require(
                component["status"] == "unavailable"
                and component["amount"] is None
                and component["currency"] == "USD"
                and component.get("reason"),
                f"Unavailable {name} quote lacks a reason",
            )
    return {
        "quotes": len(quotes),
        "pairs": len(PAIRS),
        "counties": len(expected_fips),
        "available_hedges": checked_available_hedges,
        "quotes_sha256": file_sha256(directory / "quotes.json"),
    }


def _book_revaluation(root: Path, scenario_directory: Path, book: dict, mapping: dict) -> None:
    """Revalue positions from canonical matrices, holdings, and contracts."""
    required_fips = {str(row["fips"]) for row in mapping["holdings"]}
    manifest, values, scenario_ids, columns = _scenario_matrix(
        scenario_directory, required_fips, paths=book["scenario_count"]
    )
    problem = _compile_problem(
        root,
        mapping,
        mapping["holdings"],
        values,
        scenario_ids,
        columns,
        manifest["scenario_set"]["scenario_set_id"],
    )
    optimized, components = book["optimized"], book["predictive_components"]
    positions = np.asarray(optimized["positions"], dtype=float)
    costs = problem.unit_costs
    total = np.asarray(components["total_loss"], dtype=float)
    recomputed = problem.losses - problem.payoffs @ positions + float(np.dot(positions, costs))
    require(
        optimized["status"] == "optimal" and np.isfinite(positions).all(), "Book is not optimal"
    )
    require(
        np.allclose(total, recomputed, rtol=1e-10, atol=1e-7), "Canonical book revaluation mismatch"
    )
    require(
        np.allclose(
            total, np.asarray(optimized["residual_loss"], dtype=float), rtol=1e-10, atol=1e-7
        ),
        "Book optimized residual loss is not reproducible",
    )
    require(
        np.isclose(float(optimized["deterministic_cost"]), float(np.dot(positions, costs))),
        "Book deterministic cost is not reproducible",
    )
    require(
        np.isclose(
            optimized["risk"]["expected_shortfall"],
            expected_shortfall(recomputed, problem.weights, float(mapping["tail_level"])),
        ),
        "Book expected shortfall is not reproducible",
    )
    residuals = _constraint_residuals(problem, positions)
    require(
        residuals.keys() == optimized["constraint_residuals"].keys()
        and all(
            np.isclose(residuals[key], optimized["constraint_residuals"][key]) for key in residuals
        ),
        "Book constraint report is not reproducible",
    )
    if "incremental_claim" in book:
        claim_rows = [row for row in mapping["holdings"] if row["kind"] == "claim"]
        base_rows = [row for row in mapping["holdings"] if row["kind"] != "claim"]
        base = _compile_problem(
            root,
            mapping,
            base_rows,
            values,
            scenario_ids,
            columns,
            manifest["scenario_set"]["scenario_set_id"],
            allow_constraint_subset=True,
        )
        claim_loss = np.sum([loss_on_matrix(row, values, columns) for row in claim_rows], axis=0)
        incremental = book["incremental_claim"]
        results = (incremental["book"], incremental["book_plus_claim"])
        losses = (base.losses, base.losses + claim_loss)
        costs = []
        risks = []
        for result, loss in zip(results, losses, strict=True):
            result_positions = np.asarray(result["positions"], dtype=float)
            costs.append(float(np.dot(result_positions, base.unit_costs)))
            risks.append(
                expected_shortfall(
                    loss - base.payoffs @ result_positions + costs[-1],
                    base.weights,
                    float(mapping["tail_level"]),
                )
            )
        require(
            np.isclose(incremental["incremental_cost"], costs[1] - costs[0])
            and np.isclose(incremental["incremental_es"], risks[1] - risks[0]),
            "Incremental claim report is not reproducible",
        )


def _books(
    root: Path, directory: Path, comparison_path: Path, source: Path, scenario_directory: Path
) -> dict:
    comparison = _json(comparison_path)
    require(
        comparison.get("scope") == "registered public 2000 prefix versus offline 10000",
        "Missing public/offline comparison scope",
    )
    comparisons = comparison["books"]
    public = {path.stem: _json(path) for path in (directory / "public-2000").glob("*.json")}
    offline = {path.stem: _json(path) for path in (directory / "offline-10000").glob("*.json")}
    source_blueprint = _json(source)
    source_books = {}
    for key, ref in source_blueprint["objects"].items():
        if key.startswith("book:"):
            source_books[key.split(":", 1)[1]] = ResultEnvelope.from_dict(
                _json(source.parent / ref["source_path"])
            ).payload
    require(
        set(public) == set(offline) == set(comparisons) == set(source_books) and len(public) == 3,
        "Final books incomplete",
    )
    for book_id, entry in comparisons.items():
        for label, book, paths in (
            ("public", public[book_id], 2000),
            ("offline", offline[book_id], 10000),
        ):
            require(book["scenario_count"] == paths, "Book has the wrong scenario count")
            mapping = next(
                _json(path)
                for path in (root / "config/books").glob("*.json")
                if _json(path)["book_id"] == book_id
            )
            _book_revaluation(root, scenario_directory, book, mapping)
            optimized = book["optimized"]
            require(
                entry["candidate_ids"] == book["candidate_ids"]
                and entry[f"{label}_result_id"] == book["result_id"]
                and entry[f"{label}_scenario_set_id"] == book["scenario_set_id"]
                and np.allclose(entry[f"{label}_positions"], optimized["positions"])
                and np.isclose(entry[f"{label}_cost"], optimized["deterministic_cost"])
                and np.isclose(entry[f"{label}_es"], optimized["risk"]["expected_shortfall"]),
                "Final comparison does not bind the revalued book",
            )
        require(
            source_books[book_id].get("scientific_result_id", source_books[book_id]["result_id"])
            == entry["public_result_id"],
            "Public book wrapper does not bind the compared scientific result",
        )
    return {"books": sorted(public), "comparison_sha256": file_sha256(comparison_path)}


def _research(source: Path) -> dict:
    blueprint = _json(source)
    objects = blueprint["objects"]
    required = ("research:method", "research:r01", "research:r04", "research:validation")
    records = {}
    for key in required:
        ref = objects[key]
        record = ResultEnvelope.from_dict(_json(source.parent / ref["source_path"]))
        require(
            record.result_type == "research_evidence" and record.source_artifact_ids,
            "Research evidence lacks provenance",
        )
        records[key] = record
    method = records["research:method"].payload
    require(
        {"r01", "r02", "r03", "r04", "r05", "nebraska_case"}.issubset(method),
        "Method evidence omits a registered research component",
    )
    require(
        "inconclusive" in method["r04"]["disposition"]
        and "descriptive" in method["r05"]["disposition"],
        "Public research evidence overstates its bounded findings",
    )
    require(
        records["research:validation"].payload.get("r04_origins"), "R04 origin evidence missing"
    )
    return {
        "public_records": list(required),
        "method_source_artifacts": len(records["research:method"].source_artifact_ids),
    }


def verify_candidate(root: Path, candidate_path: Path, gates: list[str]) -> dict:
    spec = _json(_path(root, str(candidate_path)))
    require(
        spec.get("schema_version") == "2.0" and spec.get("scope") == "national",
        "Candidate evidence requires explicit national scope/schema",
    )
    checks = []

    def check(name, gate, operation):
        if gate not in gates:
            return
        try:
            result = operation()
            checks.append({"name": name, "gate": gate, "status": "passed", "observed": result})
        except (ValueError, KeyError, OSError, AssertionError) as error:
            checks.append(
                {
                    "name": name,
                    "gate": gate,
                    "status": "failed",
                    "reason": f"{type(error).__name__}: {error}",
                }
            )

    check(
        "national_matched_policy_and_reference",
        "G1",
        lambda: _r01(root, _path(root, spec["r01_directory"])),
    )
    check(
        "all_scenario_chunks_and_daily_reconciliation",
        "G3",
        lambda: _scenarios(root, _path(root, spec["scenario_directory"])),
    )
    check(
        "full_quote_coverage_and_frozen_selection_alignment",
        "G2",
        lambda: _quotes(
            root,
            _path(root, spec["quotes_directory"]),
            _path(root, spec["asof_directory"]),
            _path(root, spec["scenario_directory"]),
        ),
    )
    check(
        "revalued_public_and_offline_books",
        "G4",
        lambda: _books(
            root,
            _path(root, spec["books_directory"]),
            _path(root, spec["portfolio_comparison"]),
            _path(root, spec["public_source"]),
            _path(root, spec["scenario_directory"]),
        ),
    )
    check(
        "strict_public_records_and_exact_offline_prefix",
        "G0",
        lambda: _public(
            root, _path(root, spec["public_source"]), _path(root, spec["scenario_directory"])
        ),
    )
    check(
        "public_research_evidence_and_bounded_dispositions",
        "G5",
        lambda: _research(_path(root, spec["public_source"])),
    )
    if "G8" in gates:
        from weather_basis.publishing.release import verify_release

        check("sealed_bundle", "G8", lambda: verify_release(_path(root, spec["bundle"])))
    report = {
        "scope": "national_numerical_and_bundle",
        "checks": checks,
        "status": "passed" if checks and all(x["status"] == "passed" for x in checks) else "failed",
        "limitations": (
            "Browser journeys, research interpretation and public deployment "
            "retain separate recorded evidence."
        ),
        "candidate_sha256": file_sha256(_path(root, str(candidate_path))),
    }
    report["report_id"] = content_id(report, prefix="national-acceptance")
    return report
