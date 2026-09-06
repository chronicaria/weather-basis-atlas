"""Small artificial scenarios that exercise the same V2 index/payoff/ledger paths."""
from __future__ import annotations

import numpy as np
import pandas as pd

from weather_basis.provenance.ids import content_id
from weather_basis.scenarios.common import DailyScenarioPaths, monthly_degree_day_matrix
from weather_basis.schemas.scenarios import ScenarioSet


def fixture_scenarios():
    dates = pd.date_range("2026-07-01", "2027-06-30", freq="D")
    locations = ("31109", "17031", "fixture-station-A", "fixture-station-B")
    # January index/31 * $10 gives the independently specified [10,20,40] loss.
    levels = np.array([[1, 3, 0, 2], [2, 2, 1, 1], [4, 0, 3, 0]], dtype=float)
    values = np.broadcast_to(65 - levels[:, None, :], (3, len(dates), 4)).copy()
    identity = content_id({"fixture": "perfect-weather-ledger-v1", "values": levels.tolist(),
                           "dates": [str(dates[0].date()), str(dates[-1].date())]})
    scenario_set = ScenarioSet(
        scenario_set_id=identity, scenario_type="physical_predictive",
        scenario_ids=("artificial-low", "artificial-mid", "artificial-high"),
        probability_weights=(0.25, 0.5, 0.25), calendar_id="gregorian-local-v1",
        date_start="2026-07-01", date_end="2027-06-30", location_ids=locations,
        generator_spec_id="artificial-hand-example-v1", common_random_plan_id=identity,
        data_vintage_id="artificial-fixture-v1", model_spec_ids=("hand-example",),
        valuation_asof="2026-07-01")
    paths = DailyScenarioPaths(scenario_set=scenario_set, dates=dates,
                              location_ids=locations, values=values)
    return scenario_set, monthly_degree_day_matrix(paths)
