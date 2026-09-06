"""Cheap marginal-plus-dependence candidate for the R04 pilot.

It is intentionally a monthly-index product only: it does not claim daily
paths and therefore cannot be used where daily or strip identities are needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from weather_basis.schemas.scenarios import MarginalDistribution, ScenarioMatrix, ScenarioSet


@dataclass(frozen=True)
class RankCoupledMarginalResult:
    matrix: ScenarioMatrix
    marginals: tuple[MarginalDistribution, ...]
    product_support: str = "monthly-index-only; no daily or strip identity claim"


def rank_coupled_marginals(
    *,
    historical_indexes: np.ndarray,
    entity_ids: tuple[str, ...],
    scenario_set: ScenarioSet,
    seed: int,
) -> RankCoupledMarginalResult:
    """Resample each marginal then apply whole-vector historical rank templates.

    One historical season vector supplies all entity ranks for a scenario.  This
    preserves cross-location/cross-month template dependence and zero atoms;
    independently sorted months are never joined.
    """
    source = np.asarray(historical_indexes, dtype=np.float64)
    if source.ndim != 2 or source.shape[1] != len(entity_ids) or not np.all(np.isfinite(source)):
        raise ValueError("historical indexes require complete (season, entity) support")
    if len(entity_ids) == 0:
        raise ValueError("entity ids cannot be empty")
    rng = np.random.default_rng(seed)
    n = len(scenario_set.scenario_ids)
    template = source[rng.integers(source.shape[0], size=n)]
    samples = np.column_stack(
        [source[rng.integers(source.shape[0], size=n), j] for j in range(source.shape[1])]
    )
    values = np.empty_like(samples)
    for j in range(source.shape[1]):
        # stable ordering keeps tied zero atoms deterministic.
        rank_order = np.argsort(template[:, j], kind="stable")
        values[rank_order, j] = np.sort(samples[:, j], kind="stable")
    matrix = ScenarioMatrix(
        parent_scenario_set_id=scenario_set.scenario_set_id,
        scenario_ids=scenario_set.scenario_ids,
        entity_ids=entity_ids,
        values=values,
        units="degree_days",
    )
    marginals = tuple(
        MarginalDistribution(
            parent_scenario_set_id=scenario_set.scenario_set_id,
            entity_id=entity,
            quantiles=tuple(np.sort(values[:, j])),
            units="degree_days",
        )
        for j, entity in enumerate(entity_ids)
    )
    return RankCoupledMarginalResult(matrix=matrix, marginals=marginals)
