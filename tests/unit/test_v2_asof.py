from datetime import date

import numpy as np

from weather_basis.hedge.asof import choose_from_score_tape


def test_current_recomputes_score_after_latest_historical_outcome():
    years = np.arange(2020, 2026)
    target = np.arange(6, dtype=float)[:, None]
    residuals = np.zeros((6, 1, 2))
    residuals[:5, 0, 1] = 0.1
    residuals[5, 0, 0] = 10
    args = dict(
        residuals=residuals,
        targets=target,
        seasons=years,
        station_ids=np.array(["A", "B"]),
        fips=["31109"],
        distances=np.array([[1.0, 2.0]]),
        month=1,
        first_test=np.array([2000, 2000]),
    )
    before = choose_from_score_tape(**args, valuation_date=date(2025, 1, 1))[0]
    current = choose_from_score_tape(**args, valuation_date=date(2026, 7, 1))[0]
    assert before.choice[0, 0] == 0
    assert current.choice[0, 0] == 1
    residuals[-1] = 100000
    unchanged = choose_from_score_tape(**args, valuation_date=date(2025, 1, 1))[0]
    np.testing.assert_array_equal(before.choice, unchanged.choice)
