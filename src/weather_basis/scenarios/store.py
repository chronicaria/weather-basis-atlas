"""Lazy county chunks over a release-wide, fixed common scenario coordinate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from weather_basis.contracts.calendar import PAIRS
from weather_basis.schemas.scenarios import ScenarioMatrix, ScenarioSet


@dataclass
class LazyMonthlyScenarioStore:
    """Combines county chunks only when release and scenario IDs agree exactly."""

    scenario_set: ScenarioSet
    supported_pairs: tuple[str, ...] = field(
        default_factory=lambda: tuple(pair.key for pair in PAIRS)
    )
    _chunks: dict[str, ScenarioMatrix] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if set(self.supported_pairs) != {pair.key for pair in PAIRS}:
            raise ValueError("public V2 monthly store must declare all 14 retained pairs")

    def add_chunk(self, county_id: str, matrix: ScenarioMatrix) -> None:
        matrix.assert_same_scenarios(
            ScenarioMatrix(
                parent_scenario_set_id=self.scenario_set.scenario_set_id,
                scenario_ids=self.scenario_set.scenario_ids,
                entity_ids=("coordinate-check",),
                values=[[0.0]] * len(self.scenario_set.scenario_ids),
                units="degree_days",
            )
        )
        required = {f"{county_id}:{pair}" for pair in self.supported_pairs}
        if set(matrix.entity_ids) != required or matrix.units != "degree_days":
            raise ValueError("county chunk must have exactly the 14 declared pair columns")
        self._chunks[county_id] = matrix

    def get_chunk(
        self, county_id: str, loader: Callable[[str], ScenarioMatrix] | None = None
    ) -> ScenarioMatrix:
        if county_id not in self._chunks:
            if loader is None:
                raise ValueError(f"missing scenario support for county {county_id}")
            self.add_chunk(county_id, loader(county_id))
        return self._chunks[county_id]

    def select(
        self,
        county_id: str,
        pair_keys: tuple[str, ...],
        *,
        loader: Callable[[str], ScenarioMatrix] | None = None,
    ) -> ScenarioMatrix:
        if not set(pair_keys) <= set(self.supported_pairs):
            raise ValueError("requested pair is outside the fixed 12-month scenario horizon")
        chunk = self.get_chunk(county_id, loader)
        return chunk.select(tuple(f"{county_id}:{pair}" for pair in pair_keys))
