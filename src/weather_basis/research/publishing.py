# ruff: noqa: E501, E702
"""Source-projected B20 research and B21 book/case public records.

These helpers make no release-tree writes.  The release owner can consume the
returned :class:`ResultEnvelope` objects after pinning their artifact IDs.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_basis.portfolio import (
    PortfolioProblem,
    cooling_overrun,
    frontier,
    heating_shortfall,
    incremental_capital,
    optimize,
    risk_decomposition,
)
from weather_basis.portfolio.optimize import OptimizationResult
from weather_basis.portfolio.risk import expected_shortfall
from weather_basis.provenance.artifacts import read_manifest
from weather_basis.provenance.ids import canonical_json, content_id
from weather_basis.publishing.projections import envelope
from weather_basis.schemas.public import ResultEnvelope


def _latest_artifact(root: Path, relative: str) -> tuple[Path, str]:
    candidates = sorted((root / relative).glob("*/artifact-manifest.json"))
    if not candidates:
        raise FileNotFoundError(f"No completed artifact under {relative}")
    directory = candidates[-1].parent
    return directory, read_manifest(directory).artifact_id


def _book_files(root: Path) -> list[dict[str, Any]]:
    books = []
    for path in sorted((root / "config" / "books").glob("*.json")):
        book = json.loads(path.read_text())
        if book.get("schema_version") != "2.0" or not book.get("book_id"):
            raise ValueError(f"Invalid sample book: {path}")
        books.append(book)
    if len(books) != 3:
        raise ValueError("V2 requires exactly three supplied sample books")
    return books


def sample_book_envelopes(
    root: Path,
    *,
    release_id: str,
    data_vintage_id: str = "v1-frozen",
) -> dict[str, ResultEnvelope]:
    """Return the three canonical sample books without inventing B11 scenarios."""
    _, nebraska_artifact = _latest_artifact(root, "results/v2/cases/nebraska")
    result: dict[str, ResultEnvelope] = {}
    for book in _book_files(root):
        payload = {**book, "availability": {"predictive_ledger": "unavailable",
                   "reason": book["reason_code"], "next_input": "B11 common scenario artifact"}}
        result[book["book_id"]] = envelope(
            release_id=release_id,
            result_type="book",
            payload=payload,
            analysis_id=content_id({"book": book}),
            source_artifact_ids=(nebraska_artifact,),
            data_vintage_id=data_vintage_id,
            scenario_set_id=None,
            units="USD",
            currency="USD",
            status="partial",
            reason_code=book["reason_code"],
            evidence_reference="config/books; B11 scenario compilation pending",
        )
    return result


def research_envelopes(
    root: Path,
    *,
    release_id: str,
    data_vintage_id: str = "v1-frozen",
) -> dict[str, ResultEnvelope]:
    """Project registered R02/R03/R05 reports and the Nebraska case verbatim."""
    records: dict[str, ResultEnvelope] = {}
    for name in ("R02", "R03", "R05"):
        directory, artifact_id = _latest_artifact(root, f"results/v2/experiments/{name}")
        report = json.loads((directory / "report.json").read_text())
        records[name.lower()] = envelope(
            release_id=release_id,
            result_type="research",
            payload={"registered_experiment": report, "limitations": report["scope"]},
            analysis_id=report["protocol_id"],
            source_artifact_ids=(artifact_id,),
            data_vintage_id=data_vintage_id,
            model_spec_ids=("historical-index-fit-v1",),
            scenario_set_id=None,
            units="degree_days",
            status="partial",
            reason_code="not_final_national_or_predictive_validation",
            evidence_reference=f"{directory.relative_to(root)}/report.json",
        )
    directory, artifact_id = _latest_artifact(root, "results/v2/cases/nebraska")
    case = json.loads((directory / "case.json").read_text())
    records["nebraska"] = envelope(
        release_id=release_id,
        result_type="research",
        payload={"case": case, "limitations": "Historical county/station basis; no market claim."},
        analysis_id=case["protocol_id"],
        source_artifact_ids=(artifact_id,),
        data_vintage_id=data_vintage_id,
        scenario_set_id=None,
        units="degree_days",
        status="partial",
        reason_code="predictive_common_scenarios_pending",
        evidence_reference=f"{directory.relative_to(root)}/case.json",
    )
    return records


def _json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _json_value(dataclasses.asdict(value))
    if hasattr(value, "tolist"):
        return _json_value(value.tolist())
    if isinstance(value, float):
        # Unbounded solver constraints are informative internally but cannot
        # become a nonportable JSON decision value.
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def decision_record(
    *,
    request: dict[str, Any],
    result: OptimizationResult,
    source_artifact_ids: tuple[str, ...],
    scenario_set_id: str,
    question: str,
    uncertainty: str,
    adverse_scenarios: list[str],
    maintenance_command: str,
) -> dict[str, Any]:
    """Machine-readable record that preserves actual implemented lot positions."""
    payload = {
        "schema_version": "2.0",
        "question": question,
        "request": _json_value(request),
        "result": _json_value(result),
        "source_artifact_ids": list(source_artifact_ids),
        "scenario_set_id": scenario_set_id,
        "uncertainty": uncertainty,
        "adverse_scenarios": adverse_scenarios,
        "maintenance_command": maintenance_command,
    }
    payload["decision_id"] = content_id(payload, prefix="decision")
    return payload


def decision_memo(record: dict[str, Any], *, html: bool = False) -> str:
    """Render one decision record without recomputing or rounding its values."""
    result = record["result"]
    risk = result.get("risk") or {}
    positions = result.get("positions")
    lines = [
        "# Portfolio decision memo",
        f"\n## Question\n\n{record['question']}",
        f"\n## Decision identity\n\n`{record['decision_id']}` · scenario `{record['scenario_set_id']}`",
        "\n## Holdings and implementation\n",
        f"\nPositions: `{json.dumps(positions)}`\n\nStatus: `{result['status']}`; objective: `{result['objective']}`.",
        "\n## Cost and risk\n",
        f"\nDeterministic cost: `{result.get('deterministic_cost')}`; ES: `{risk.get('expected_shortfall')}`; variance: `{risk.get('variance')}`.",
        f"\n## Binding constraints\n\n{', '.join(result.get('binding_constraints', [])) or 'None reported'}.",
        f"\n## Adverse scenarios\n\n{'; '.join(record['adverse_scenarios']) or 'None supplied'}.",
        f"\n## Uncertainty\n\n{record['uncertainty']}",
        f"\n## Reproduction\n\nSources: {', '.join(record['source_artifact_ids'])}. Run `{record['maintenance_command']}`.",
    ]
    markdown = "\n".join(lines) + "\n"
    if not html:
        return markdown
    body = markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<!doctype html><html><body><pre>{body}</pre></body></html>\n"


def export_decision(directory: Path, record: dict[str, Any]) -> dict[str, Path]:
    """Export result/request JSON and holdings/result CSV without precision loss."""
    directory.mkdir(parents=True, exist_ok=True)
    request_path, result_path = directory / "request.json", directory / "result.json"
    request_path.write_text(canonical_json(record["request"]) + "\n")
    result_path.write_text(canonical_json(record) + "\n")
    holdings_path = directory / "holdings.csv"
    holdings = record["request"].get("holdings", [])
    fields = ("row_id", "kind", "entity_id", "amount", "units", "currency")
    with holdings_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(holdings)
    rows_path = directory / "result.csv"
    with rows_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("candidate_id", "position"))
        for candidate, position in zip(record["request"].get("candidate_ids", []), record["result"].get("positions") or [], strict=True):
            writer.writerow((candidate, repr(position)))
    return {"request": request_path, "result": result_path, "holdings": holdings_path, "rows": rows_path}


def restore_decision(path: Path) -> dict[str, Any]:
    record = json.loads(Path(path).read_text())
    expected = record.pop("decision_id", None)
    actual = content_id(record, prefix="decision")
    if expected != actual:
        raise ValueError("Decision manifest identity mismatch")
    record["decision_id"] = expected
    return record


def decisions_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return canonical_json(left) == canonical_json(right)


_LOCAL_STATIONS = {
    "31055": "USW00014942",
    "31109": "USW00014939",
    "31079": "USW00014935",
    "31111": "USW00024023",
    "31157": "USW00024028",
}


def _load_chunk(path: Path) -> tuple[np.ndarray, tuple[str, ...], tuple[str, ...], str]:
    chunk = np.load(path, allow_pickle=False)
    values = np.asarray(chunk["values"], dtype=np.float64)
    scenario_ids = tuple(str(value) for value in chunk["scenario_ids"])
    entities = tuple(str(value) for value in chunk["entity_ids"])
    parent = str(chunk["parent_scenario_set_id"][0])
    if values.shape != (len(scenario_ids), len(entities)):
        raise ValueError(f"scenario chunk lacks aligned values: {path}")
    return values, scenario_ids, entities, parent


def _scenario_matrix(directory: Path, required_fips: set[str] | None = None, paths: int | None = None) -> tuple[dict[str, Any], np.ndarray, tuple[str, ...], dict[str, int]]:
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("kind") == "bounded-common-scenario-artifact":
        matrix = np.load(directory / manifest["monthly_matrix"]["file"], allow_pickle=False)
        values = np.asarray(matrix["values"], dtype=np.float64)
        scenario_ids = tuple(str(value) for value in matrix["scenario_ids"])
        entities = tuple(str(value) for value in matrix["entity_ids"])
        if values.shape != (len(scenario_ids), len(entities)) or not np.isfinite(values).all():
            raise ValueError("B11 monthly matrix lacks finite common support")
        normalized = {**manifest, "artifact_id": manifest["artifact_id"], "production_status": manifest["production_status"]}
    elif manifest.get("kind") == "r2j-production-stream":
        chunks_by_fips = manifest["county_chunks"]
        requested = set(chunks_by_fips) if required_fips is None else set(required_fips)
        if requested - set(chunks_by_fips):
            raise ValueError(f"R2j artifact lacks requested county chunks: {sorted(requested - set(chunks_by_fips))}")
        files = [directory / chunks_by_fips[fips] for fips in sorted(requested)]
        files.append(directory / manifest["station_chunk"])
        chunks = [_load_chunk(path) for path in files]
        values, scenario_ids, entities, parent = chunks[0]
        values = np.column_stack([item[0] for item in chunks])
        entities = tuple(entity for _, _, columns, _ in chunks for entity in columns)
        if any(item[1] != scenario_ids or item[3] != parent for item in chunks[1:]):
            raise ValueError("R2j chunks do not share an exact scenario identity")
        scenario_set_id = str(manifest["scenario_set"]["scenario_set_id"])
        if parent != scenario_set_id:
            raise ValueError("R2j chunk parent scenario identity differs from manifest")
        if paths is not None:
            if paths not in (int(manifest.get("public_paths", -1)), int(manifest["paths"])):
                raise ValueError("R2j stream supports only its registered public prefix or full path count")
            values, scenario_ids = values[:paths], scenario_ids[:paths]
            if paths != int(manifest["paths"]):
                subset_id = content_id({"parent": scenario_set_id, "paths": paths, "rule": manifest["public_slice_rule"]})
                manifest = {**manifest, "scenario_set": {**manifest["scenario_set"], "scenario_set_id": subset_id, "parent_scenario_set_id": scenario_set_id}}
        normalized = {**manifest, "artifact_id": content_id(manifest, prefix="r2j-production"), "production_status": manifest.get("status", "unknown")}
    else:
        raise ValueError("sample books require B11 matrix or R2j production chunks")
    if len(set(entities)) != len(entities):
        raise ValueError("scenario artifact has duplicate entity coordinates")
    return normalized, values, scenario_ids, {entity: index for index, entity in enumerate(entities)}


def _loss(row: dict[str, Any], index: np.ndarray) -> np.ndarray:
    if row["loss_kind"] == "heating_shortfall":
        return heating_shortfall(index, row["budget"], row["amount"])
    if row["loss_kind"] == "cooling_overrun":
        return cooling_overrun(index, row["budget"], row["amount"], cap=row.get("claim_cap_usd"))
    if row["loss_kind"] == "asymmetric_deviation":
        cold, hot = row["cold_amount"], row["hot_amount"]
        return cold * np.maximum(row["budget"] - index, 0.0) + hot * np.maximum(index - row["budget"], 0.0)
    raise ValueError(f"unsupported loss_kind: {row.get('loss_kind')}")


def loss_on_matrix(row: dict[str, Any], values: np.ndarray, columns: dict[str, int]) -> np.ndarray:
    """Canonical exposure/claim liability on aligned monthly index columns."""
    if row["loss_kind"] != "contract_payoff":
        return _loss(row, values[:, columns[row["entity_id"]]])
    from weather_basis.portfolio import payoffs

    spec = row["payoff_spec"]; members = row.get("member_entity_ids", [row["entity_id"]])
    if not 1 <= len(members) <= 12 or len(set(members)) != len(members):
        raise ValueError("contract claim requires 1–12 unique member entities")
    if row["payoff_structure"] == "monthly_option" and len(members) != 1:
        raise ValueError("monthly contract claim requires exactly one member")
    indexes = np.column_stack([values[:, columns[entity]] for entity in members])
    strike, multiplier = float(spec["strike"]), float(spec["multiplier"])
    def option(index: np.ndarray) -> np.ndarray:
        kind = spec["kind"]
        if kind == "linear":
            return payoffs.linear(index, float(spec.get("entry_level", strike)), multiplier)
        if kind in {"call", "capped_call"}:
            return payoffs.call(index, strike, multiplier, spec.get("cap"))
        if kind in {"put", "capped_put"}:
            return payoffs.put(index, strike, multiplier, spec.get("cap"))
        if kind == "call_spread":
            return payoffs.call_spread(index, strike, float(spec["high_strike"]), multiplier)
        if kind == "put_spread":
            return payoffs.put_spread(index, strike, float(spec["low_strike"]), multiplier)
        if kind == "collar":
            return payoffs.collar(index, strike, float(spec["call_strike"]), multiplier)
        raise ValueError(f"unsupported contract payoff kind: {kind}")
    structure = row["payoff_structure"]
    if structure == "option_on_strip":
        result = option(indexes.sum(axis=1))
    elif structure in {"monthly_option", "sum_of_monthly_options"}:
        result = option(indexes).sum(axis=1)
    else:
        raise ValueError(f"unsupported payoff_structure: {structure}")
    return float(row.get("direction", 1.0)) * result


def _station_for_row(root: Path, row: dict[str, Any], columns: dict[str, int]) -> str:
    explicit = row.get("station_id")
    if explicit:
        return str(explicit)
    mapped = _LOCAL_STATIONS.get(row["fips"])
    if mapped:
        return mapped
    counties = pd.read_csv(root / "data/metadata/counties.csv", dtype={"fips": str}).set_index("fips")
    registry = pd.read_csv(root / "data/metadata/station_registry.csv", dtype={"ghcnd_id": str})
    available = sorted({entity.split(":", 1)[0] for entity in columns if entity.startswith("US")})
    candidates = registry.loc[registry.ghcnd_id.isin(available)]
    if row["fips"] not in counties.index or candidates.empty:
        raise ValueError(f"no explicit or registry-supported station for {row['fips']}")
    county = counties.loc[row["fips"]]
    distance = (candidates.lat - county.lat) ** 2 + (candidates.lon - county.lon) ** 2
    return str(candidates.loc[distance.idxmin(), "ghcnd_id"])


def _candidate_contract(root: Path, book: dict[str, Any], row: dict[str, Any], columns: dict[str, int]) -> dict[str, Any]:
    station = _station_for_row(root, row, columns)
    contract = {"station_entity_id": f"{station}:{row['pair']}", "payoff": "put" if row["loss_kind"] == "heating_shortfall" else "call", "loss_kind": row["loss_kind"], "strike": float(row["budget"]), "multiplier_usd_per_degree_day": float(book["option_contract"]["payout_usd_per_degree_day"]), "contract_spec_id": book["option_contract"]["contract_spec_id"]}
    return {"candidate_id": content_id(contract, prefix="candidate-contract"), **contract}


def _compile_problem(
    root: Path,
    book: dict[str, Any],
    rows: list[dict[str, Any]],
    values: np.ndarray,
    scenario_ids: tuple[str, ...],
    columns: dict[str, int],
    scenario_set_id: str,
    constraints: dict[str, Any] | None = None,
    allow_constraint_subset: bool = False,
) -> PortfolioProblem:
    losses = np.zeros(len(scenario_ids))
    candidate_ids: list[str] = []
    payoff_columns: list[np.ndarray] = []
    for row in rows:
        entity = row["entity_id"]
        if entity != f"{row['fips']}:{row['pair']}":
            raise ValueError("book entity_id must be exact FIPS:PAIR coordinate")
        if entity not in columns:
            raise ValueError(f"B11 artifact lacks exposure coordinate {entity}")
        county_index = values[:, columns[entity]]
        if not np.isfinite(county_index).all():
            raise ValueError(f"scenario artifact lacks finite exposure coordinate {entity}")
        losses += loss_on_matrix(row, values, columns)
        if row["kind"] == "claim":
            continue
        contract = _candidate_contract(root, book, row, columns)
        station_entity = contract["station_entity_id"]
        if station_entity not in columns:
            raise ValueError(f"B11 artifact lacks local station support for {row['fips']}")
        if contract["candidate_id"] in candidate_ids:
            continue
        station_index = values[:, columns[station_entity]]
        if not np.isfinite(station_index).all():
            raise ValueError(f"scenario artifact lacks finite local station coordinate {station_entity}")
        multiplier = contract["multiplier_usd_per_degree_day"]
        payoff_columns.append(multiplier * (
            np.maximum(row["budget"] - station_index, 0.0)
            if row["loss_kind"] == "heating_shortfall"
            else np.maximum(station_index - row["budget"], 0.0)
        ))
        candidate_ids.append(contract["candidate_id"])
    policy = book["cost_policy"]
    fee = float(policy["contract_fee_usd"])
    unit_costs = np.asarray([float(np.mean(payoff)) + fee for payoff in payoff_columns])
    if policy.get("zero_cost_sensitivity") is True:
        unit_costs = np.zeros(len(candidate_ids))
    problem = PortfolioProblem(
        losses=losses,
        payoffs=np.column_stack(payoff_columns),
        scenario_ids=scenario_ids,
        candidate_ids=tuple(candidate_ids),
        unit_costs=unit_costs,
        upper_bounds=np.full(len(candidate_ids), 1_000_000.0),
        max_active=len(candidate_ids),
        max_stations=len(candidate_ids),
        scenario_type="physical_predictive",
    )
    if not constraints:
        return problem
    candidate_ids = problem.candidate_ids
    def aligned(name: str) -> np.ndarray:
        raw = constraints[name]
        if isinstance(raw, dict):
            if not allow_constraint_subset and set(raw) - set(candidate_ids):
                raise ValueError(f"{name} includes an unknown candidate")
            return np.asarray([raw.get(candidate, 0.0) for candidate in candidate_ids], dtype=float)
        if np.isscalar(raw):
            return np.full(len(candidate_ids), float(raw))
        return np.asarray(raw, dtype=float)
    vector_fields = ("lower_bounds", "upper_bounds", "lot_sizes", "reference_positions")
    text_fields = ("station_ids", "region_ids")
    overrides: dict[str, Any] = {}
    for name in vector_fields:
        if name in constraints:
            overrides[name] = aligned(name)
    for name in text_fields:
        if name in constraints:
            raw = constraints[name]
            overrides[name] = tuple(raw.get(candidate, candidate) for candidate in candidate_ids) if isinstance(raw, dict) else ((str(raw),) * len(candidate_ids) if isinstance(raw, str) else tuple(raw))
    for name in ("cash_budget", "gross_limit", "net_lower", "net_upper", "allow_short", "max_active", "turnover_limit", "station_limits", "region_limits", "max_stations"):
        if name in constraints:
            overrides[name] = constraints[name]
    return dataclasses.replace(problem, **overrides)


def compile_book(root: Path, scenario_dir: Path, book_mapping: dict[str, Any], *, cost_policy: dict[str, Any] | None = None, constraints: dict[str, Any] | None = None, paths: int | None = None) -> dict[str, Any]:
    """Compile one canonical or caller-supplied book from an existing scenario artifact."""
    root = Path(root)
    required_fips = {str(row["fips"]) for row in book_mapping["holdings"]}
    required_fips.update(
        str(entity).split(":")[0]
        for row in book_mapping["holdings"]
        for entity in row.get("member_entity_ids", ())
    )
    manifest, values, scenario_ids, columns = _scenario_matrix(Path(scenario_dir), required_fips, paths)
    scenario_set_id = manifest["scenario_set"]["scenario_set_id"]
    book = {**book_mapping, "cost_policy": cost_policy or book_mapping["cost_policy"]}
    objective, alpha = book["objective"], float(book["tail_level"])
    es_target = book.get("es_target")
    if objective == "min_cost_es":
        if not isinstance(es_target, (int, float)) or not math.isfinite(es_target) or es_target < 0:
            raise ValueError("book objective min_cost_es requires a finite non-negative es_target")
        es_target = float(es_target)
    elif es_target is not None:
        raise ValueError("es_target is only valid with objective min_cost_es")
    def solve(candidate: PortfolioProblem, target: float | None = es_target) -> OptimizationResult:
        return optimize(candidate, objective, alpha=alpha, es_target=target)
    rows = book["holdings"]
    problem = _compile_problem(root, book, rows, values, scenario_ids, columns, scenario_set_id, constraints)
    baseline = np.zeros(len(problem.candidate_ids))
    solved = solve(problem)
    if objective == "min_cost_es":
        targets = tuple(float(value) for value in book.get("frontier_es_targets", (es_target,)))
        if not targets or any(not math.isfinite(value) or value < 0 for value in targets):
            raise ValueError("frontier_es_targets must be finite non-negative targets")
        frontier_result = {"dimension": "es_target", "points": [_json_value(solve(problem, value)) for value in targets]}
    else:
        cost = float(solved.deterministic_cost or 0.0)
        budgets = tuple(float(value) for value in book.get("frontier_budgets", (0.0, cost * .25, cost * .5, cost * .75, cost)))
        budgets = tuple(sorted(set(budgets)))
        frontier_result = {"dimension": "cash_budget", "points": _json_value(frontier(problem, budgets, objective, alpha=alpha))}
    first_upper = np.zeros(len(problem.candidate_ids)); first_upper[0] = problem.upper_bounds[0]
    first_exposure_station = solve(dataclasses.replace(problem, upper_bounds=first_upper))
    single = solve(dataclasses.replace(problem, max_active=1))
    basket = solve(dataclasses.replace(problem, max_active=min(2, len(problem.candidate_ids))))
    exposure_components = np.column_stack([loss_on_matrix(row, values, columns) for row in rows])
    gross_exposure = exposure_components.sum(axis=1)
    positions = np.asarray(solved.positions if solved.positions is not None else np.zeros(len(problem.candidate_ids)))
    hedge_payoff = problem.payoffs @ positions
    frozen_cost = float(solved.deterministic_cost or 0.0)
    standalone = {row["row_id"]: float(expected_shortfall(exposure_components[:, index], problem.weights, alpha)) for index, row in enumerate(rows)}
    natural_diversification = {"standalone_es": standalone, "gross_book_es": float(expected_shortfall(gross_exposure, problem.weights, alpha)), "sum_standalone_es_minus_gross_book_es": float(sum(standalone.values()) - expected_shortfall(gross_exposure, problem.weights, alpha)), "interpretation": "Predictive diversification diagnostic only; distinct from hedge benefit and not an allocation."}
    contracts = {contract["candidate_id"]: contract for row in rows for contract in [_candidate_contract(root, book, row, columns)] if contract["candidate_id"] in problem.candidate_ids}
    result: dict[str, Any] = {
        "schema_version": "2.0", "book_id": book["book_id"], "status": "available",
        "scenario_set_id": scenario_set_id, "scenario_count": len(scenario_ids),
        "scenario_artifact_id": manifest["artifact_id"], "production_status": manifest["production_status"],
        "cost_policy": book["cost_policy"], "option_contract": book["option_contract"],
        "candidate_payoff_units": "USD",
        "candidate_ids": list(problem.candidate_ids),
        "candidate_unit_costs": dict(zip(problem.candidate_ids, (float(value) for value in problem.unit_costs), strict=True)),
        "candidate_contracts": contracts,
        "predictive_components": {"exposure_losses": {row["row_id"]: exposure_components[:, index].tolist() for index, row in enumerate(rows)}, "gross_exposure_loss": gross_exposure.tolist(), "hedge_payoff": hedge_payoff.tolist(), "frozen_cost": [frozen_cost] * len(scenario_ids), "total_loss": (gross_exposure - hedge_payoff + frozen_cost).tolist()},
        "natural_diversification": natural_diversification,
        "baseline": _json_value(risk_decomposition(problem, baseline, alpha=alpha)),
        "options": {"no_hedge": _json_value(risk_decomposition(problem, baseline, alpha=alpha)), "first_exposure_station": _json_value(first_exposure_station), "best_single": _json_value(single), "two_station_basket": _json_value(basket), "declared_local_station_basket": _json_value(solved), "optimized": _json_value(solved)},
        "optimized": _json_value(solved),
        "frontier": frontier_result,
        "holdings": rows,
    }
    claim_rows = [row for row in rows if row["kind"] == "claim"]
    if claim_rows:
        without_claim = [row for row in rows if row["kind"] != "claim"]
        base_problem = _compile_problem(root, book, without_claim, values, scenario_ids, columns, scenario_set_id, constraints, True)
        claim_loss = np.sum([loss_on_matrix(row, values, columns) for row in claim_rows], axis=0)
        if objective == "min_cost_es":
            base = solve(base_problem); combined = solve(dataclasses.replace(base_problem, losses=base_problem.losses + claim_loss))
            result["incremental_claim"] = _json_value({"book": base, "book_plus_claim": combined, "incremental_es": None if base.risk is None or combined.risk is None else combined.risk.expected_shortfall - base.risk.expected_shortfall, "incremental_cost": None if base.deterministic_cost is None or combined.deterministic_cost is None else combined.deterministic_cost - base.deterministic_cost})
        else:
            result["incremental_claim"] = _json_value(incremental_capital(base_problem, claim_loss, objective, alpha=alpha))
    result["result_id"] = content_id(result, prefix="book-result")
    return result


def compile_sample_books(root: Path, scenario_dir: Path, out: Path, *, paths: int | None = None) -> dict[str, dict[str, Any]]:
    """Compile all supplied books against one supplied B11 common matrix.

    It does not simulate weather.  A valid input produces available finite
    ledger results, while its representative-only production status remains in
    the output for the release owner to gate separately.
    """
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    compiled: dict[str, dict[str, Any]] = {}
    for book in _book_files(root):
        result = compile_book(root, scenario_dir, book, paths=paths)
        target = out / f"{book['book_id']}.json"
        target.write_text(canonical_json(result) + "\n")
        request = {
            "book_id": book["book_id"], "holdings": book["holdings"],
            "candidate_ids": list(result["candidate_unit_costs"]),
            "cost_policy": book["cost_policy"],
        }
        record = decision_record(
            request=request, result=result["optimized"],
            source_artifact_ids=(result["scenario_artifact_id"],),
            scenario_set_id=result["scenario_set_id"], question=book["question"],
            uncertainty="Representative physical predictive scenarios and illustrative physical expected-payout pricing; no observed or executable market quote.",
            adverse_scenarios=["Scenario-level tail attribution is available from the retained scenario-set identity; this memo does not relabel physical paths as market prices."],
            maintenance_command=f"uv run python -c \"from pathlib import Path; from weather_basis.research.publishing import compile_sample_books; compile_sample_books(Path('.'), Path('{scenario_dir}'), Path('{out}'))\"",
        )
        decision_dir = out / book["book_id"]
        export_decision(decision_dir, record)
        (decision_dir / "memo.md").write_text(decision_memo(record))
        (decision_dir / "memo.html").write_text(decision_memo(record, html=True))
        compiled[book["book_id"]] = result
    return compiled


def evaluate_scenario_room(book_result: dict[str, Any], room_envelope: dict[str, Any]) -> dict[str, Any]:
    """Reevaluate frozen book cashflows on observed/stress room weather; never optimize or price."""
    payload = room_envelope.get("payload", room_envelope)
    monthly = payload["monthly_degree_days"]
    values = np.asarray(monthly["values"], dtype=float)
    scenario_ids = tuple(monthly["scenario_ids"])
    columns = {str(entity): index for index, entity in enumerate(monthly["entity_ids"])}
    positions = dict(zip(book_result["candidate_ids"], book_result["optimized"]["positions"], strict=True))
    exposures = np.zeros((len(scenario_ids), len(book_result["holdings"])))
    for index, row in enumerate(book_result["holdings"]):
        entity = row["entity_id"]
        if entity not in columns:
            raise ValueError(f"Scenario Room lacks exposure coordinate {entity}")
        exposures[:, index] = loss_on_matrix(row, values, columns)
    hedge = np.zeros(len(scenario_ids))
    for candidate, contract in book_result["candidate_contracts"].items():
        entity = contract["station_entity_id"]
        if entity not in columns:
            raise ValueError(f"Scenario Room lacks contract coordinate {entity}")
        index = values[:, columns[entity]]; strike = contract["strike"]; multiplier = contract["multiplier_usd_per_degree_day"]
        payoff = multiplier * (np.maximum(strike - index, 0.0) if contract["payoff"] == "put" else np.maximum(index - strike, 0.0))
        hedge += float(positions[candidate]) * payoff
    gross = exposures.sum(axis=1); cost = float(book_result["optimized"]["deterministic_cost"] or 0.0); residual = gross - hedge + cost
    rows = [{"scenario_id": scenario_ids[i], "exposure_components": {row["row_id"]: float(exposures[i, j]) for j, row in enumerate(book_result["holdings"])}, "gross_exposure_loss": float(gross[i]), "hedge_payoff": float(hedge[i]), "frozen_cost": cost, "total_loss": float(residual[i])} for i in range(len(scenario_ids))]
    scenario_type = payload["scenario_set"]["scenario_type"]
    return {"schema_version": "2.0", "producer": "scenario-room-frozen-book-cashflow-v1", "book_result_id": book_result["result_id"], "room_scenario_set_id": payload["scenario_set"]["scenario_set_id"], "room_scenario_type": scenario_type, "cost_policy": book_result["cost_policy"], "candidate_ids": book_result["candidate_ids"], "candidate_contracts": book_result["candidate_contracts"], "rows": rows, "components": {"exposure_losses": {row["row_id"]: exposures[:, j].tolist() for j, row in enumerate(book_result["holdings"])}, "gross_exposure_loss": gross.tolist(), "hedge_payoff": hedge.tolist(), "frozen_cost": [cost] * len(scenario_ids), "total_loss": residual.tolist()}, "natural_diversification": None, "risk_metrics": None, "risk_reason": "stress has null weights" if scenario_type == "stress" else "historical rows are descriptive only; predictive ES is not computed"}
