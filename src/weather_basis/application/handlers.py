"""Registered stage adapters. Unavailable dependencies fail without hidden refitting."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np

from weather_basis.provenance.ids import canonical_json, file_sha256


def _write(out, name, data):
    path = out / name
    path.write_text(canonical_json(_plain(data)) + "\n")
    return path


def _plain(value):
    if dataclasses.is_dataclass(value):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _dependency(context, stage, filename):
    matches = [
        path / filename
        for path in context.dependency_directories.get(stage, [])
        if (path / filename).is_file()
    ]
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one {stage}/{filename} dependency; found {len(matches)}")
    return matches[0]


def _fixture_problem():
    from weather_basis.application.fixtures import fixture_scenarios
    from weather_basis.portfolio.ledger import PortfolioProblem
    from weather_basis.schemas.scenarios import ScenarioMatrix

    scenario_set, matrix = fixture_scenarios()
    target = matrix.select(("31109:HDD-01",))
    station = matrix.select(("fixture-station-A:HDD-01",))
    losses = ScenarioMatrix(
        parent_scenario_set_id=matrix.parent_scenario_set_id,
        scenario_ids=matrix.scenario_ids,
        entity_ids=("illustrative-loss",),
        values=target.values * 10 / 31,
        units="USD",
    )
    payoffs = ScenarioMatrix(
        parent_scenario_set_id=matrix.parent_scenario_set_id,
        scenario_ids=matrix.scenario_ids,
        entity_ids=station.entity_ids,
        values=station.values * 10 / 31,
        units="USD",
    )
    return PortfolioProblem.from_matrices(
        losses,
        payoffs,
        weights=np.asarray(scenario_set.probability_weights),
        unit_costs=np.array([0.0]),
        fixed_cost=2.0,
        upper_bounds=np.array([2.0]),
    )


def dispatch_stage(stage, context, out):
    mode = context.request["mode"]
    if stage == "inputs.audit":
        from weather_basis.schemas.vintages import VintageLock

        vintage = VintageLock.from_dict(context.vintage)
        result = {
            "schema_version": "2.0",
            "scope": mode,
            "vintage_id": vintage.vintage_id,
            "inputs": context.input_artifacts,
            "support": [s.to_dict() for s in vintage.support],
            "market_data_status": vintage.market_data_status,
            "official_settlement_status": vintage.official_settlement_status,
        }
        return [_write(out, "audit.json", result)]
    if stage == "panels.prepare":
        if mode == "fixture":
            from .fixtures import fixture_scenarios

            scenarios, matrix = fixture_scenarios()
            return [
                _write(out, "scenario_set.json", scenarios.to_dict()),
                _write(out, "indexes.json", matrix.to_dict()),
            ]
        import pyarrow.parquet as pq

        pairs = context.request["pairs"] or context.research["pairs"]
        records = []
        for pair in pairs:
            for kind in ("county", "station"):
                path = context.root / f"results/indices/{kind}_{pair}.parquet"
                records.append(
                    {
                        "pair": pair,
                        "kind": kind,
                        "path": str(path),
                        "sha256": file_sha256(path),
                        "rows": pq.read_metadata(path).num_rows,
                    }
                )
        return [_write(out, "panels.json", {"scope": mode, "indexes": records})]
    if stage == "atlas.evaluate":
        if mode == "fixture":
            from weather_basis.hedge.evaluation import evaluate_policy, matched_comparison
            from weather_basis.hedge.policies import choose_policy

            target = np.array([[0.0], [1.0], [2.0], [3.0]])
            residual = np.array([[[0.0, 0.0]], [[0.0, 1.0]], [[1.0, np.nan]], [[np.nan, 1.0]]])
            eligible = np.ones_like(residual, dtype=bool)
            left = choose_policy(
                "prior_best",
                decision_eligible=eligible,
                prior_scores=np.broadcast_to([2.0, 1.0], residual.shape),
                nearest_station=np.array([1]),
            )
            right = choose_policy(
                "nearest_eligible",
                decision_eligible=eligible,
                prior_scores=np.zeros_like(residual),
                nearest_station=np.array([1]),
            )
            evaluations = [
                evaluate_policy(
                    d,
                    target=target,
                    residual_by_station=residual,
                    evaluation_scoreable=np.isfinite(residual),
                )
                for d in (left, right)
            ]
            comparison = matched_comparison(*evaluations, target)
            return [
                _write(
                    out,
                    "comparisons.json",
                    {
                        "fixture": True,
                        "common_seasons": comparison.season_ids,
                        "left_he": comparison.left_he,
                        "right_he": comparison.right_he,
                        "denominator": comparison.denominator,
                    },
                )
            ]
        from weather_basis.hedge.national import reconstruct_national

        reconstruct_national(
            context.root, pairs=tuple(context.request["pairs"]) or None, out_dir=out
        )
        from weather_basis.hedge.summary import summarize_r01

        summarize_r01(out)
        return None
    if stage in ("models.fit", "tournament.execute", "models.select"):
        if mode == "fixture":
            # The artificial generator is fixed by the hand example. It has no fitted weather claim.
            from .fixtures import fixture_scenarios

            scenario_set, _ = fixture_scenarios()
            return [
                _write(
                    out,
                    f"{stage.split('.')[0]}.json",
                    {
                        "scope": "artificial_fixture",
                        "generator_spec_id": scenario_set.generator_spec_id,
                        "fitting": "not_applicable_hand_specified_paths",
                        "source_artifact_ids": list(context.input_artifacts.values()),
                    },
                )
            ]
        # Production candidate selection consumes the registered R04 outcome; it cannot invent one.
        from weather_basis.application.models import handle_model_stage

        return handle_model_stage(stage, context, out)
    if stage == "scenarios.build":
        if mode == "fixture":
            from .fixtures import fixture_scenarios

            scenarios, matrix = fixture_scenarios()
            return [
                _write(out, "scenario_set.json", scenarios.to_dict()),
                _write(out, "indexes.json", matrix.to_dict()),
            ]
        from weather_basis.application.models import handle_scenarios

        return handle_scenarios(context, out)
    if stage == "payoffs.build":
        if mode == "fixture":
            return [_write(out, "problem.json", _fixture_problem())]
        from weather_basis.application.portfolios import handle_payoffs

        return handle_payoffs(context, out)
    if stage in ("portfolios.evaluate", "portfolios.optimize"):
        if mode == "fixture":
            from weather_basis.portfolio.optimize import optimize

            problem = _fixture_problem()
            if stage.endswith("optimize"):
                result = optimize(
                    problem, context.request["objective"], alpha=context.research["tail_level"]
                )
            else:
                from weather_basis.portfolio.ledger import residual_loss
                from weather_basis.portfolio.risk import risk_statistics

                result = {
                    "positions": [1.0],
                    "residual_loss": residual_loss(problem, np.ones(1)),
                    "risk": risk_statistics(residual_loss(problem, np.ones(1)), problem.weights),
                }
            return [_write(out, "portfolio_result.json", result)]
        from weather_basis.application.portfolios import handle_portfolios

        return handle_portfolios(stage, context, out)
    if stage in (
        "atlas.select_asof",
        "quotes.build",
        "cases.build",
        "site.build",
        "release.verify",
    ):
        from weather_basis.application.publishing import handle_publishing_stage

        return handle_publishing_stage(stage, context, out)
    if stage == "research.next_station":
        from weather_basis.application.research import handle_next_station

        return handle_next_station(context, out)
    raise ValueError(f"No registered implementation for {stage}")
