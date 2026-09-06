"""Descriptive diagnostics for B20 generator selection.

They intentionally report marginal and dependence evidence separately.  They
are not a model-selection rule and must be evaluated on registered holdouts.
"""

from __future__ import annotations

import numpy as np

from weather_basis.schemas.scenarios import ScenarioMatrix


def _same_entities(reference: ScenarioMatrix, candidate: ScenarioMatrix) -> None:
    if reference.units != candidate.units or reference.entity_ids != candidate.entity_ids:
        raise ValueError("diagnostics require identical ordered entities and units")


def marginal_diagnostics(reference: ScenarioMatrix, candidate: ScenarioMatrix) -> dict[str, object]:
    """Return per-entity mean/scale/quantile differences without a joint score."""
    _same_entities(reference, candidate)
    quantiles = np.asarray((0.05, 0.50, 0.95))
    ref_q = np.quantile(reference.values, quantiles, axis=0)
    candidate_q = np.quantile(candidate.values, quantiles, axis=0)
    return {
        "kind": "marginal",
        "units": reference.units,
        "entity_ids": reference.entity_ids,
        "mean_difference": tuple(
            np.mean(candidate.values, axis=0) - np.mean(reference.values, axis=0)
        ),
        "std_difference": tuple(
            np.std(candidate.values, axis=0) - np.std(reference.values, axis=0)
        ),
        "quantiles": tuple(float(item) for item in quantiles),
        "quantile_difference": tuple(tuple(row) for row in candidate_q - ref_q),
    }


def dependence_diagnostics(
    reference: ScenarioMatrix, candidate: ScenarioMatrix
) -> dict[str, object]:
    """Return covariance and common upper-tail co-occurrence differences."""
    _same_entities(reference, candidate)
    if len(reference.entity_ids) < 2:
        raise ValueError("dependence diagnostics need at least two entities")
    reference_covariance = np.cov(reference.values, rowvar=False, ddof=0)
    candidate_covariance = np.cov(candidate.values, rowvar=False, ddof=0)
    ref_upper = reference.values >= np.quantile(reference.values, 0.9, axis=0)
    candidate_upper = candidate.values >= np.quantile(candidate.values, 0.9, axis=0)
    ref_tail = ref_upper.astype(float).T @ ref_upper.astype(float) / len(reference.scenario_ids)
    candidate_tail = (
        candidate_upper.astype(float).T
        @ candidate_upper.astype(float)
        / len(candidate.scenario_ids)
    )
    return {
        "kind": "dependence",
        "units": reference.units,
        "entity_ids": reference.entity_ids,
        "covariance_difference": tuple(
            tuple(row) for row in candidate_covariance - reference_covariance
        ),
        "upper_tail_cooccurrence_difference": tuple(
            tuple(row) for row in candidate_tail - ref_tail
        ),
    }
