"""Scenario coordinates are identities, never inferred from equal array lengths."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .base import StrictRecord, require


@dataclass(frozen=True, kw_only=True)
class ScenarioSet(StrictRecord):
    scenario_set_id: str
    scenario_type: str
    scenario_ids: tuple[str, ...]
    probability_weights: tuple[float, ...] | None
    calendar_id: str
    date_start: str
    date_end: str
    location_ids: tuple[str, ...]
    generator_spec_id: str
    common_random_plan_id: str
    data_vintage_id: str
    model_spec_ids: tuple[str, ...]
    valuation_asof: str
    scenario_id_hash: str = ""
    seed_schema_version: str = "v2-seed-1"
    local_date_policy: str = "local-observation-date"
    variable_units: tuple[str, ...] = ("temperature:degF",)
    conditioning_information_ids: tuple[str, ...] = ()
    support_policy: str = "complete-common-support"
    dtype: str = "float64"
    content_artifact_ids: tuple[str, ...] = ()
    calibration_id: str | None = None

    def __post_init__(self):
        super().__post_init__()
        require(
            self.scenario_type
            in ("historical", "physical_predictive", "market_calibrated_proxy", "stress"),
            "Invalid scenario type",
        )
        require(
            len(self.scenario_ids) > 0 and len(set(self.scenario_ids)) == len(self.scenario_ids),
            "Scenario IDs must be nonempty and unique",
        )
        require(len(set(self.location_ids)) == len(self.location_ids), "Duplicate locations")
        require(self.date_start <= self.date_end, "Invalid date horizon")
        if self.probability_weights is None:
            require(self.scenario_type == "stress", "Predictive/historical sets require weights")
        else:
            weights = np.asarray(self.probability_weights, dtype=np.float64)
            require(weights.shape == (len(self.scenario_ids),), "Weight shape mismatch")
            require(
                bool(np.all(weights >= 0)) and abs(float(weights.sum()) - 1) < 1e-10,
                "Nonnegative scenario probabilities must sum to one",
            )


@dataclass(frozen=True, kw_only=True)
class ScenarioMatrix:
    parent_scenario_set_id: str
    scenario_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    values: np.ndarray
    units: str
    schema_version: str = "2.0"
    dtype: str = "float64"
    missing_support_policy: str = "reject"
    matrix_kind: str = "aligned"

    def __post_init__(self):
        require(self.schema_version == "2.0", "Unsupported matrix schema")
        require(self.matrix_kind == "aligned", "Sorted marginals are not aligned matrices")
        require(self.missing_support_policy == "reject", "Missing holdings cannot be dropped")
        require(self.units in ("degF", "degree_days", "USD"), "Unsupported matrix units")
        require(
            len(set(self.scenario_ids)) == len(self.scenario_ids) > 0,
            "Duplicate/empty scenario coordinates",
        )
        require(
            len(set(self.entity_ids)) == len(self.entity_ids) > 0,
            "Duplicate/empty entity coordinates",
        )
        values = np.array(self.values, dtype=np.float64, copy=True)
        require(
            values.shape == (len(self.scenario_ids), len(self.entity_ids)),
            "Scenario matrix shape mismatch",
        )
        require(bool(np.all(np.isfinite(values))), "Missing/nonfinite matrix support")
        values.flags.writeable = False
        object.__setattr__(self, "values", values)

    def assert_same_scenarios(self, other: ScenarioMatrix) -> None:
        require(isinstance(other, ScenarioMatrix), "Expected aligned ScenarioMatrix")
        require(
            self.parent_scenario_set_id == other.parent_scenario_set_id,
            "Different parent scenario sets",
        )
        require(self.scenario_ids == other.scenario_ids, "Scenario coordinate mismatch")

    def select(self, entity_ids: tuple[str, ...]) -> ScenarioMatrix:
        require(set(entity_ids) <= set(self.entity_ids), "Requested entity lacks scenario support")
        return ScenarioMatrix(
            parent_scenario_set_id=self.parent_scenario_set_id,
            scenario_ids=self.scenario_ids,
            entity_ids=entity_ids,
            values=self.values[:, [self.entity_ids.index(e) for e in entity_ids]],
            units=self.units,
        )

    def to_dict(self):
        from weather_basis.provenance.ids import content_id

        return {
            "schema_version": self.schema_version,
            "parent_scenario_set_id": self.parent_scenario_set_id,
            "scenario_ids": list(self.scenario_ids),
            "entity_ids": list(self.entity_ids),
            "scenario_id_hash": content_id(list(self.scenario_ids)),
            "entity_id_hash": content_id(list(self.entity_ids)),
            "shape": list(self.values.shape),
            "values": self.values.tolist(),
            "units": self.units,
            "dtype": self.dtype,
            "missing_support_policy": self.missing_support_policy,
            "matrix_kind": self.matrix_kind,
        }

    @classmethod
    def from_dict(cls, data):
        from weather_basis.provenance.ids import content_id

        fields = {
            "schema_version",
            "parent_scenario_set_id",
            "scenario_ids",
            "entity_ids",
            "scenario_id_hash",
            "entity_id_hash",
            "shape",
            "values",
            "units",
            "dtype",
            "missing_support_policy",
            "matrix_kind",
        }
        require(set(data) == fields, "Unknown or missing matrix fields")
        require(
            data["scenario_id_hash"] == content_id(data["scenario_ids"]), "Scenario hash mismatch"
        )
        require(data["entity_id_hash"] == content_id(data["entity_ids"]), "Entity hash mismatch")
        result = cls(
            **{
                k: (tuple(v) if k in ("scenario_ids", "entity_ids") else v)
                for k, v in data.items()
                if k not in ("scenario_id_hash", "entity_id_hash", "shape")
            }
        )
        require(list(result.values.shape) == data["shape"], "Declared shape mismatch")
        return result


@dataclass(frozen=True, kw_only=True)
class MarginalDistribution:
    """Display-only sorted view; deliberately does not implement the aligned API."""

    parent_scenario_set_id: str
    entity_id: str
    quantiles: tuple[float, ...]
    units: str
