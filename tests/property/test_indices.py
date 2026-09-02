"""Property tests for plan Sections 5.3 and 6.2 index/anomaly invariants."""

from __future__ import annotations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from weather_basis.indices.anomalies import anomaly, trailing_normal
from weather_basis.indices.county import monthly_indices

temperatures = st.floats(min_value=-50, max_value=120, allow_nan=False, allow_infinity=False)
series_values = st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False)


@given(st.lists(temperatures, min_size=1, max_size=28))
def test_hdd_cdd_daily_identity(values: list[float]) -> None:
    """Plan Section 5.3: HDD minus CDD equals base minus temperature every day."""
    tbar = np.asarray(values)[:, None]
    dates = np.arange("2021-01-01", "2021-02-01", dtype="datetime64[D]")[: len(values)]
    hdd = monthly_indices(tbar, dates, ["HDD-01"])["HDD-01"][1][0, 0]
    cdd = monthly_indices(tbar, dates, ["CDD-01"])["CDD-01"][1][0, 0]
    assert np.isclose(hdd - cdd, np.sum(65.0 - tbar[:, 0]))


@given(
    st.lists(series_values, min_size=16, max_size=60),
    series_values,
)
def test_anomaly_is_translation_invariant(values: list[float], shift: float) -> None:
    """Plan Section 6.2: adding a constant shifts normals but not anomalies."""
    x = np.asarray(values)
    np.testing.assert_allclose(
        anomaly(x, min_prior=15), anomaly(x + shift, min_prior=15), equal_nan=True
    )
    np.testing.assert_allclose(
        trailing_normal(x + shift, min_prior=15),
        trailing_normal(x, min_prior=15) + shift,
        equal_nan=True,
    )
