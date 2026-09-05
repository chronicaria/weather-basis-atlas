"""Enforces plan Sections 7.1, 7.4, 7.5, and 7.6."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from weather_basis.models.index_parametric import fit_index_parametric, simulate_index_parametric
from weather_basis.models.joint import joint_block_plan
from weather_basis.models.scoring import crps_from_samples
from weather_basis.models.simulate import block_plan, simulate_month
from weather_basis.models.tournament import SkillInterval, select_rung
from weather_basis.scenarios.r2j_production import (
    PAIR_ORDER,
    _last_complete_raw_state,
    _propagate_chunk,
)
from weather_basis.validation.holdout import HoldoutLock


def test_r1_fit_and_draws_are_censored() -> None:
    rng = np.random.default_rng(4)
    seasons = np.arange(50)
    values = 30 + 2 * seasons + rng.standard_t(7, size=50)
    fit = fit_index_parametric(values, seasons=seasons)
    draws = simulate_index_parametric(fit, season=51, M=1000, rng=rng)
    assert fit.nu >= 4
    assert np.all(draws >= 0)
    assert abs(fit.slope - 2) < 0.2


def test_block_plan_is_seeded_and_joint_indices_are_shared() -> None:
    rng = np.random.default_rng(99)
    plan = block_plan(rng, M=400, n_days=100, mean_block=7, candidate_days=np.arange(1000))
    plan_again = block_plan(
        np.random.default_rng(99), M=400, n_days=100, mean_block=7, candidate_days=np.arange(1000)
    )
    assert np.array_equal(plan.indices, plan_again.indices)
    observed_lengths = plan.lengths[plan.lengths > 0]
    assert 5 < observed_lengths.mean() < 8
    joint = joint_block_plan(
        np.random.default_rng(99),
        M=4,
        n_days=10,
        mean_block=7,
        valid_z=np.ones((1000, 3), dtype=bool),
    )
    assert joint.indices.shape == (4, 10)


def test_simulate_month_streams_simple_zero_ar_process() -> None:
    plan = block_plan(
        np.random.default_rng(1), M=3, n_days=2, mean_block=7, candidate_days=np.arange(2)
    )
    z = np.ones((2, 1))
    result = simulate_month(
        z,
        plan=plan,
        sigma=np.ones((2, 1)),
        ar=np.zeros((1, 5)),
        mean=np.full((2, 1), 60.0),
        init_state=None,
        series_slice=slice(None),
        accumulate_mask=np.ones(2, dtype=bool),
        index_fn=lambda t: np.maximum(65 - t, 0),
    )
    assert result.shape == (3, 1)
    assert np.allclose(result, 8)


def test_r2j_streamer_months_match_independent_simulate_month_masks() -> None:
    """The production one-pass loop retains V1's sigma-before-AR recurrence."""
    rng = np.random.default_rng(17)
    dates = pd.date_range("2026-07-01", "2027-06-30", freq="D")
    paths, history, series = 4, 400, 2
    rows = rng.integers(0, history, size=(paths, len(dates)), dtype=np.int32)
    plan = block_plan(
        np.random.default_rng(3),
        M=paths,
        n_days=len(dates),
        mean_block=7,
        candidate_days=np.arange(history),
    )
    plan = plan.__class__(indices=rows, starts=plan.starts, lengths=plan.lengths)
    z = rng.normal(size=(history, series))
    sigma = rng.uniform(0.3, 2.0, size=(len(dates), series))
    mean = rng.uniform(45.0, 75.0, size=(len(dates), series))
    ar = np.array([[0.35, -0.12], [0.2, 0.05]])
    initial = np.array([[1.0, -0.5], [0.25, 0.75]])

    totals, audit = _propagate_chunk(
        z=z,
        plan_rows=rows,
        sigma=sigma,
        mean=mean,
        coefficients=ar,
        initial=initial,
        dates=dates,
        audit_count=2,
    )
    assert audit.shape == (2, len(dates), series)
    for index, (_, kind, month) in enumerate(PAIR_ORDER):
        expected = simulate_month(
            z,
            plan=plan,
            sigma=sigma,
            ar=ar,
            mean=mean,
            init_state=initial,
            series_slice=slice(None),
            accumulate_mask=dates.month.to_numpy() == month,
            index_fn=(
                (lambda temp: np.maximum(65.0 - temp, 0.0))
                if kind == "HDD"
                else (lambda temp: np.maximum(temp - 65.0, 0.0))
            ),
        )
        np.testing.assert_allclose(totals[:, :, index], expected, rtol=0, atol=0)


def test_r2j_initial_state_uses_latest_complete_observations() -> None:
    raw = np.array([[1.0], [2.0], [np.nan], [4.0], [5.0]])
    state, endpoints = _last_complete_raw_state(
        raw, pd.date_range("2026-01-01", periods=5), lags=2
    )
    np.testing.assert_array_equal(state[:, 0], [5.0, 4.0])
    assert endpoints == ("2026-01-05",)


def test_crps_matches_bruteforce_formula() -> None:
    x = np.array([-1.0, 0.0, 2.0, 5.0])
    y = 1.5
    brute = np.mean(abs(x - y)) - np.mean(abs(x[:, None] - x[None, :])) / 2
    assert crps_from_samples(x, y) == pytest.approx(brute)


def test_ladder_selection_is_sequential() -> None:
    win = SkillInterval(0.1, 0.01, 0.2, 32)
    fail = SkillInterval(0.2, -0.01, 0.4, 32)
    assert select_rung(fail, win) == "R0"
    assert select_rung(win, fail) == "R1"
    assert select_rung(win, win) == "R2"


def test_holdout_refuses_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    lock = HoldoutLock()
    with pytest.raises(PermissionError):
        lock.check([2022, 2023])
    monkeypatch.setenv("WBA_UNLOCK_HOLDOUT", "1")
    lock.check(2023)
