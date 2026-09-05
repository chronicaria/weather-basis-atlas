"""B26's registered, bounded next-station pilot.

The pilot is deliberately historical and retrospective.  It does not infer
exchange availability from a GHCN observation, and it freezes each decision
before looking at that origin's realized county or station index.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from weather_basis.portfolio import PortfolioProblem, optimize
from weather_basis.portfolio.ledger import deterministic_cost, residual_loss
from weather_basis.portfolio.payoffs import put
from weather_basis.portfolio.risk import risk_statistics
from weather_basis.provenance.ids import canonical_json, content_id

PROTOCOL_PATH = Path("config/research/next-station-v2.yaml")


def load_protocol(root: Path) -> dict[str, Any]:
    """Read the separately frozen B26 registration, rejecting malformed basics."""
    protocol = yaml.safe_load((Path(root) / PROTOCOL_PATH).read_text())
    if (
        not isinstance(protocol, dict)
        or protocol.get("experiment_id") != "B26-next-station-nebraska-v1"
    ):
        raise ValueError("invalid B26 next-station protocol")
    if len(protocol["baseline"]["station_ids"]) != 13:
        raise ValueError("B26 baseline must contain exactly 13 station IDs")
    if len(protocol["candidate_admission"]["station_ids"]) != 5:
        raise ValueError("B26 must predeclare exactly five candidate station IDs")
    if protocol["constraints"]["upper_contracts_per_station"] <= 0:
        raise ValueError("B26 requires finite positive contract bounds")
    return protocol


def _annual_matrix(frame: pd.DataFrame, item: str, ids: list[str], years: np.ndarray) -> np.ndarray:
    values = frame.pivot(index=item, columns="season", values="index").reindex(
        index=ids, columns=years
    )
    return values.to_numpy(dtype=float).T


def _station_registry(root: Path, ids: list[str]) -> pd.DataFrame:
    registry = pd.read_csv(Path(root) / "data/metadata/station_registry.csv")
    records = registry.set_index("ghcnd_id").reindex(ids)
    if records.isna().any(axis=None):
        missing = records.index[records.isna().any(axis=1)].tolist()
        raise ValueError(f"B26 station metadata missing: {missing}")
    return records


def admission_table(root: Path, protocol: dict[str, Any]) -> list[dict[str, Any]]:
    """Verify the registered 13+5 split and disclose each proxy's metadata/QC source."""
    baseline = list(protocol["baseline"]["station_ids"])
    candidates = list(protocol["candidate_admission"]["station_ids"])
    if set(baseline) & set(candidates):
        raise ValueError("B26 additions overlap the declared baseline")
    registry = _station_registry(root, baseline + candidates)
    if set(registry.loc[baseline, "role"]) != {"cme"}:
        raise ValueError("B26 baseline IDs do not resolve to the registry's CME panel")
    if set(registry.loc[candidates, "role"]) != {protocol["candidate_admission"]["required_role"]}:
        raise ValueError("B26 candidate IDs do not resolve to registered Nebraska additions")
    source_manifest = pd.read_csv(Path(root) / "data/manifests/ghcnd_stations.csv")
    source_manifest["station_id"] = source_manifest.path.str.removeprefix(
        "data/raw/ghcnd/"
    ).str.removesuffix(".csv")
    source_rows = source_manifest.set_index("station_id")
    result = []
    for station_id, row in registry.loc[candidates].iterrows():
        source = source_rows.loc[station_id] if station_id in source_rows.index else None
        result.append(
            {
                "station_id": station_id,
                "name": row["name"],
                "latitude": float(row["lat"]),
                "longitude": float(row["lon"]),
                "elevation_m": float(row["elev_m"]),
                "registry_role": row["role"],
                "admission_status": "research_proxy_pending_origin_qc",
                "availability_disclosure": (
                    "observed public research proxy; no exchange availability claim"
                ),
                "source_operational": {
                    "source_artifact_id": "ghcnd-stations-manifest-v1",
                    "source_record_present": source is not None,
                    "source_sha256": None if source is None else source["sha256"],
                    "source_retrieved_at_utc": None
                    if source is None
                    else source["retrieved_at_utc"],
                    "source_url": None if source is None else source["url"],
                },
            }
        )
    return result


def _origin_qc_ok(qc: pd.DataFrame, station_ids: list[str], years: np.ndarray) -> bool:
    """January HDD has a complete, unfilled raw monthly observation for every train season."""
    rows = qc.loc[(qc.ghcnd_id.isin(station_ids)) & (qc.year.isin(years)) & (qc.month == 1)]
    expected = len(station_ids) * len(years)
    return (
        len(rows) == expected
        and rows.qc_status.eq("complete").all()
        and rows.n_gap_filled.fillna(0).eq(0).all()
    )


def _problem(
    losses: np.ndarray,
    station_indexes: np.ndarray,
    station_ids: list[str],
    *,
    fee: float,
    protocol: dict[str, Any],
) -> PortfolioProblem:
    contract = protocol["contract"]
    strikes = np.median(station_indexes, axis=0)
    payoffs = put(station_indexes, strikes, contract["payout_usd_per_dd"])
    # The physical premium is estimated only from the prior training rows.
    costs = payoffs.mean(axis=0) + fee
    constraints = protocol["constraints"]
    return PortfolioProblem(
        losses=losses,
        payoffs=payoffs,
        scenario_ids=tuple(f"train-{i}" for i in range(len(losses))),
        candidate_ids=tuple(station_ids),
        unit_costs=costs,
        upper_bounds=np.full(
            len(station_ids), constraints["upper_contracts_per_station"], dtype=float
        ),
        lot_sizes=np.full(len(station_ids), constraints["lot_size_contracts"], dtype=float),
        cash_budget=float(constraints["cash_budget_usd"]),
        allow_short=not bool(constraints["long_only"]),
        scenario_type="observed_history",
    )


def freeze_choice(
    losses: np.ndarray,
    station_indexes: np.ndarray,
    station_ids: list[str],
    *,
    objective: str,
    protocol: dict[str, Any],
    fee: float | None = None,
) -> dict[str, Any]:
    """Fit the long-only finite hedge using only prior observations.

    This compact kernel is also the selection boundary exercised by tests.  It
    has no held-out values in its arguments, preventing outcome-driven fallback.
    """
    fee = float(protocol["contract"]["contract_fee_usd"] if fee is None else fee)
    problem = _problem(losses, station_indexes, station_ids, fee=fee, protocol=protocol)
    alpha = float(protocol["tail_level"])
    # The common portfolio kernel's quadratic integer refinement intentionally
    # refuses large 13--18 column enumerations.  Preserve finite whole lots for
    # variance by flooring its feasible continuous solution and reevaluating the
    # actual ledger; ES uses the kernel's integer linear program directly.
    solved = optimize(problem, objective, alpha=alpha, lots=objective == "es")
    result = asdict(solved)
    if objective == "variance" and solved.positions is not None:
        positions = np.floor(solved.positions / problem.lot_sizes) * problem.lot_sizes
        actual_loss = residual_loss(problem, positions)
        actual_risk = risk_statistics(actual_loss, problem.weights, alpha=alpha)
        result.update(
            {
                "status": "feasible_suboptimal",
                "positions": positions,
                "residual_loss": actual_loss,
                "deterministic_cost": deterministic_cost(problem, positions),
                "risk": asdict(actual_risk),
                "objective_value": actual_risk.variance,
                "message": (
                    "continuous variance solution floored to whole contracts and reevaluated"
                ),
            }
        )
    for key, value in tuple(result.items()):
        if isinstance(value, np.ndarray):
            result[key] = value.tolist()
        elif hasattr(value, "__dict__"):
            result[key] = asdict(value)
    return {
        "candidate_ids": station_ids,
        "strikes": strikes.tolist()
        if (strikes := np.median(station_indexes, axis=0)) is not None
        else [],
        "unit_costs": problem.unit_costs.tolist(),
        "objective": objective,
        "fee_usd": fee,
        "lot_policy": protocol["constraints"]["variance_lot_rule"]
        if objective == "variance"
        else "integer_linear_program",
        "solution": result,
    }


def score_frozen_choice(
    choice: dict[str, Any],
    *,
    heldout_loss: float,
    heldout_indexes: np.ndarray,
    protocol: dict[str, Any],
) -> dict[str, Any]:
    """Score one already-frozen choice once; missing outcomes are explicitly unscoreable."""
    indexes = np.asarray(heldout_indexes, dtype=float)
    if not np.isfinite(heldout_loss) or not np.isfinite(indexes).all():
        return {"status": "unscoreable_missing_heldout_outcome", "residual_loss": None}
    positions = choice["solution"].get("positions")
    if positions is None:
        return {"status": "unscoreable_infeasible_training_choice", "residual_loss": None}
    payoffs = put(indexes, np.asarray(choice["strikes"]), protocol["contract"]["payout_usd_per_dd"])
    cost = float(np.dot(np.asarray(choice["unit_costs"]), np.abs(np.asarray(positions))))
    # Signed ledger: L - long payoff + one origin's premium/fee cost.
    value = float(heldout_loss - np.dot(payoffs, positions) + cost)
    return {"status": "scored", "residual_loss": value, "deterministic_cost": cost}


def _metric(losses: np.ndarray, objective: str, alpha: float) -> float:
    """One historical-origin metric; origins, never station rows, are observations."""
    weights = np.full(len(losses), 1.0 / len(losses))
    risk = risk_statistics(losses, weights, alpha=alpha)
    return risk.variance if objective == "variance" else risk.expected_shortfall


def paired_origin_gain(
    baseline: np.ndarray,
    challenger: np.ndarray,
    *,
    objective: str,
    alpha: float,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    """Paired gain and a descriptive bootstrap that resamples whole origins."""
    baseline, challenger = np.asarray(baseline, dtype=float), np.asarray(challenger, dtype=float)
    if len(baseline) != len(challenger) or not len(baseline):
        raise ValueError("paired origin vectors must be non-empty and aligned")
    point = _metric(baseline, objective, alpha) - _metric(challenger, objective, alpha)
    if len(baseline) < 2:
        return {"gain": float(point), "ci95": [None, None], "paired_origins": len(baseline)}
    rng = np.random.default_rng(seed)
    draws = np.empty(resamples)
    for draw in range(resamples):
        selected = rng.integers(0, len(baseline), size=len(baseline))
        draws[draw] = _metric(baseline[selected], objective, alpha) - _metric(
            challenger[selected], objective, alpha
        )
    return {
        "gain": float(point),
        "ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
        "paired_origins": len(baseline),
    }


def summarize_pilot_rows(rows: list[dict[str, Any]], protocol: dict[str, Any]) -> dict[str, Any]:
    """Create paired-origin, coverage, cost and disagreement tables from frozen rows."""
    alpha = float(protocol["tail_level"])
    uncertainty = protocol["uncertainty"]
    scored = [row for row in rows if row.get("status") == "scored"]
    summary: list[dict[str, Any]] = []
    objectives = protocol["objectives"]
    strategies = [item["id"] for item in protocol["comparisons"]]
    sensitivities = ("base", "zero_fee")
    for objective in objectives:
        for sensitivity in sensitivities:
            baseline = {
                row["origin"]: row["residual_loss"]
                for row in scored
                if row["objective"] == objective
                and row["sensitivity"] == sensitivity
                and row["strategy"] == "baseline"
            }
            for strategy in strategies:
                challenger = {
                    row["origin"]: row["residual_loss"]
                    for row in scored
                    if row["objective"] == objective
                    and row["sensitivity"] == sensitivity
                    and row["strategy"] == strategy
                }
                origins = sorted(set(baseline) & set(challenger))
                paired = (
                    None
                    if not origins
                    else paired_origin_gain(
                        np.asarray([baseline[origin] for origin in origins]),
                        np.asarray([challenger[origin] for origin in origins]),
                        objective=objective,
                        alpha=alpha,
                        resamples=int(uncertainty["resamples"]),
                        seed=int(uncertainty["seed"]),
                    )
                )
                all_rows = [
                    row
                    for row in rows
                    if row.get("objective") == objective
                    and row.get("sensitivity") == sensitivity
                    and row.get("strategy") == strategy
                ]
                missing = sum(
                    row.get("status") == "unscoreable_missing_heldout_outcome" for row in all_rows
                )
                costs = [
                    row["deterministic_cost"]
                    for row in scored
                    if row["objective"] == objective
                    and row["sensitivity"] == sensitivity
                    and row["strategy"] == strategy
                ]
                summary.append(
                    {
                        "objective": objective,
                        "sensitivity": sensitivity,
                        "strategy": strategy,
                        "registered_origins": len(protocol["rolling_evaluation"]["origins"]),
                        "strategy_scored_origins": len(challenger),
                        "baseline_scored_origins": len(baseline),
                        "paired_origins": len(origins),
                        "missing_heldout_outcomes": missing,
                        "paired_gain": paired,
                        "mean_deterministic_cost": None if not costs else float(np.mean(costs)),
                    }
                )
    selected = [
        row
        for row in scored
        if row["strategy"] == "training_selected_one_addition" and row["sensitivity"] == "base"
    ]
    by_origin = {
        objective: {
            row["origin"]: row.get("selected_addition")
            for row in selected
            if row["objective"] == objective
        }
        for objective in objectives
    }
    shared = sorted(set(by_origin["variance"]) & set(by_origin["es"]))
    disagreement = {
        "common_scored_origins": len(shared),
        "same_addition_origins": sum(
            by_origin["variance"][origin] == by_origin["es"][origin] for origin in shared
        ),
        "different_addition_origins": sum(
            by_origin["variance"][origin] != by_origin["es"][origin] for origin in shared
        ),
        "per_origin": [
            {
                "origin": origin,
                "variance_addition": by_origin["variance"][origin],
                "es_addition": by_origin["es"][origin],
            }
            for origin in shared
        ],
    }
    return {
        "objective_summary": summary,
        "cost_table": [
            row
            for row in summary
            if row["strategy"]
            in {
                "add_USW00014935",
                "add_USW00014939",
                "add_USW00014942",
                "add_USW00024023",
                "add_USW00024028",
                "fixed_combo_omaha_scottsbluff",
            }
        ],
        "variance_vs_es_disagreement": disagreement,
        "cluster_unit": "origin",
        "uncertainty_disclosure": uncertainty["note"],
    }


def adjudicate(summary: dict[str, Any], protocol: dict[str, Any]) -> str:
    """Apply only the registered B26 disposition rules; never tune after results."""
    minimum = int(protocol["adjudication"]["minimum_paired_origins"])
    records = summary["objective_summary"]
    selected = {
        row["objective"]: row
        for row in records
        if row["strategy"] == "training_selected_one_addition" and row["sensitivity"] == "base"
    }
    usable = [row for row in records if row["paired_origins"] >= minimum]
    if not usable:
        return "stop_missing_evidence"
    if set(selected) == {"variance", "es"}:
        bounds = [selected[name]["paired_gain"] for name in ("variance", "es")]
        if all(
            item is not None
            and item["paired_origins"] >= minimum
            and item["ci95"][0] is not None
            and item["ci95"][0] > 0
            for item in bounds
        ):
            return "promote"
        if all(item is not None and item["gain"] > 0 for item in bounds):
            return "retain_research"
    return "inconclusive"


def _select_addition(
    losses: np.ndarray,
    indexes: np.ndarray,
    baseline: list[str],
    candidates: list[str],
    *,
    objective: str,
    protocol: dict[str, Any],
) -> str | None:
    best: tuple[float, str] | None = None
    all_ids = baseline + candidates
    for candidate in candidates:
        selected = baseline + [candidate]
        columns = [all_ids.index(item) for item in selected]
        choice = freeze_choice(
            losses, indexes[:, columns], selected, objective=objective, protocol=protocol
        )
        solved = choice["solution"]
        value = solved.get("objective_value")
        if solved["status"] in {"optimal", "feasible_suboptimal"} and value is not None:
            trial = (float(value), candidate)
            if best is None or trial < best:
                best = trial
    return None if best is None else best[1]


def run_pilot(
    root: Path, protocol: dict[str, Any] | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute the registered historical B26 calculation after the core is accepted."""
    root = Path(root)
    protocol = protocol or load_protocol(root)
    pair = protocol["exposure_book"]["pair"]
    county = pd.read_parquet(root / f"results/indices/county_{pair}.parquet")
    station = pd.read_parquet(root / f"results/indices/station_{pair}.parquet")
    county["fips"] = county.fips.astype(str).str.zfill(5)
    baseline, candidates = (
        list(protocol["baseline"]["station_ids"]),
        list(protocol["candidate_admission"]["station_ids"]),
    )
    all_ids = baseline + candidates
    present = set(station.ghcnd_id.astype(str))
    if set(all_ids) - present:
        raise ValueError(
            f"B26 station panel is missing registered IDs: {sorted(set(all_ids) - present)}"
        )
    exposures = protocol["exposure_book"]["counties"]
    fipses = [item["fips"] for item in exposures]
    amounts = np.asarray([item["amount_usd_per_dd"] for item in exposures], dtype=float)
    years = np.asarray(sorted(set(county.season) & set(station.season)), dtype=int)
    y = _annual_matrix(county, "fips", fipses, years)
    x = _annual_matrix(station, "ghcnd_id", all_ids, years)
    qc = pd.read_parquet(root / "data/panel/station_qc.parquet")
    rows: list[dict[str, Any]] = []
    common_min = int(protocol["candidate_admission"]["minimum_common_prior_seasons"])
    for origin in protocol["rolling_evaluation"]["origins"]:
        train_years = np.arange(
            origin - int(protocol["rolling_evaluation"]["prior_seasons"]), origin
        )
        train_ix = np.flatnonzero(np.isin(years, train_years))
        heldout_ix = np.flatnonzero(years == origin)
        if len(heldout_ix) != 1:
            continue
        common = np.isfinite(y[train_ix]).all(axis=1) & np.isfinite(x[train_ix]).all(axis=1)
        qc_ok = _origin_qc_ok(qc, all_ids, train_years)
        admission = (
            "admitted" if common.sum() >= common_min and qc_ok else "ineligible_prior_support_or_qc"
        )
        for objective in protocol["objectives"]:
            if admission != "admitted":
                rows.append(
                    {
                        "origin": origin,
                        "objective": objective,
                        "strategy": "all",
                        "admission": admission,
                        "status": "not_run",
                    }
                )
                continue
            county_strikes = np.median(y[train_ix], axis=0)
            train_loss = (np.maximum(county_strikes - y[train_ix], 0.0) * amounts).sum(axis=1)[
                common
            ]
            train_x = x[train_ix][common]
            strategies: list[tuple[str, list[str]]] = [("baseline", baseline)]
            strategies += [(f"add_{item}", baseline + [item]) for item in candidates]
            strategies.append(
                ("fixed_combo_omaha_scottsbluff", baseline + ["USW00014942", "USW00024028"])
            )
            selected = _select_addition(
                train_loss, train_x, baseline, candidates, objective=objective, protocol=protocol
            )
            if selected is not None:
                strategies.append(("training_selected_one_addition", baseline + [selected]))
            for strategy, ids in strategies:
                columns = [all_ids.index(item) for item in ids]
                choice = freeze_choice(
                    train_loss, train_x[:, columns], ids, objective=objective, protocol=protocol
                )
                heldout_loss = float(
                    (np.maximum(county_strikes - y[heldout_ix[0]], 0.0) * amounts).sum()
                )
                scored = score_frozen_choice(
                    choice,
                    heldout_loss=heldout_loss,
                    heldout_indexes=x[heldout_ix[0], columns],
                    protocol=protocol,
                )
                for sensitivity, fee in (
                    ("base", protocol["contract"]["contract_fee_usd"]),
                    ("zero_fee", 0.0),
                ):
                    active_choice = (
                        choice
                        if sensitivity == "base"
                        else freeze_choice(
                            train_loss,
                            train_x[:, columns],
                            ids,
                            objective=objective,
                            protocol=protocol,
                            fee=fee,
                        )
                    )
                    active_score = (
                        scored
                        if sensitivity == "base"
                        else score_frozen_choice(
                            active_choice,
                            heldout_loss=heldout_loss,
                            heldout_indexes=x[heldout_ix[0], columns],
                            protocol=protocol,
                        )
                    )
                    rows.append(
                        {
                            "origin": origin,
                            "objective": objective,
                            "strategy": strategy,
                            "selected_addition": selected
                            if strategy == "training_selected_one_addition"
                            else None,
                            "sensitivity": sensitivity,
                            "admission": admission,
                            "common_training_seasons": int(common.sum()),
                            "choice": active_choice,
                            **active_score,
                        }
                    )
    summaries = summarize_pilot_rows(rows, protocol)
    disposition = adjudicate(summaries, protocol)
    station_table = admission_table(root, protocol)
    report = {
        "experiment": "B26",
        "protocol_id": content_id(protocol),
        "scope": protocol["scope_disclosure"],
        "admission_table": station_table,
        "consumed_development_years": protocol["reporting"]["consumed_development_years"],
        "disposition": disposition,
        "adjudication": protocol["adjudication"],
        "uncertainty": protocol["uncertainty"],
        **summaries,
        "case_page_payload": {
            "case": "Nebraska next station",
            "question": protocol["question"],
            "disposition": disposition,
            "station_map": station_table,
            "objective_summary": summaries["objective_summary"],
            "cost_table": summaries["cost_table"],
            "variance_vs_es_disagreement": summaries["variance_vs_es_disagreement"],
            "limitations": protocol["scope_disclosure"],
        },
    }
    return report, rows


def write_pilot(root: Path, out: Path) -> list[Path]:
    report, rows = run_pilot(root)
    out.mkdir(parents=True, exist_ok=True)
    report_path, rows_path = out / "next_station_report.json", out / "next_station_rows.json"
    report_path.write_text(canonical_json(report) + "\n")
    rows_path.write_text(canonical_json(rows) + "\n")
    return [report_path, rows_path]
