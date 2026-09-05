import numpy as np
import pytest

from weather_basis.schemas.base import validate_fips
from weather_basis.schemas.config import ResearchConfig
from weather_basis.schemas.scenarios import ScenarioMatrix


def test_scientific_records_reject_drift_and_nonfinite():
    config = ResearchConfig()
    assert ResearchConfig.from_dict(config.to_dict()) == config
    for update in (
        {"workers": 2},
        {"tail_level": float("nan")},
        {"seed": True},
        {"schema_version": "3.0"},
        {"currency": "EUR"},
    ):
        with pytest.raises(ValueError):
            ResearchConfig.from_dict({**config.to_dict(), **update})
    with pytest.raises(ValueError):
        validate_fips(31109)


def test_aligned_matrix_rejects_independent_sorted_and_missing_support():
    matrix = ScenarioMatrix(
        parent_scenario_set_id="s",
        scenario_ids=("a", "b"),
        entity_ids=("31109",),
        values=np.array([[1], [2]]),
        units="degree_days",
    )
    assert not matrix.values.flags.writeable
    with pytest.raises(ValueError, match="coordinate"):
        matrix.assert_same_scenarios(
            ScenarioMatrix(
                parent_scenario_set_id="s",
                scenario_ids=("b", "a"),
                entity_ids=("17031",),
                values=np.array([[3], [4]]),
                units="degree_days",
            )
        )
    with pytest.raises(ValueError, match="lacks"):
        matrix.select(("17031",))
    with pytest.raises(ValueError, match="Sorted"):
        ScenarioMatrix(
            parent_scenario_set_id="s",
            scenario_ids=("a",),
            entity_ids=("x",),
            values=np.array([[1]]),
            units="degree_days",
            matrix_kind="sorted",
        )
