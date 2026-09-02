"""Enforces plan Sections 7.1, 7.4, 7.5, and 7.6."""

from __future__ import annotations

import numpy as np
import pytest

from weather_basis.models.index_parametric import fit_index_parametric, simulate_index_parametric
from weather_basis.models.joint import joint_block_plan
from weather_basis.models.scoring import crps_from_samples
from weather_basis.models.simulate import block_plan, simulate_month
from weather_basis.models.tournament import SkillInterval, select_rung
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
