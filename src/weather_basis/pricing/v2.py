"""V2 availability-first physical and station-hedged research indications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from weather_basis.contracts.windows import resolve_contract_window
from weather_basis.hedge.policies import choose_policy
from weather_basis.portfolio.payoffs import PayoffNode, evaluate


@dataclass(frozen=True)
class V2Payoff:
    kind: Literal["linear", "call", "put", "capped_call", "capped_put"]
    strike: float = 0.0
    cap: float | None = None
    multiplier: float = 20.0
    entry_level: float | None = None


@dataclass(frozen=True)
class SelectionAsOfV2:
    valuation_date: date
    contract_window_id: str
    contract_year: int
    observation_cutoff: date
    metadata_cutoff: date
    choice_station_index: int
    selected_station_id: str | None
    reason: str


@dataclass(frozen=True)
class PriceComponent:
    name: str
    status: Literal["available", "unavailable"]
    amount: float | None
    method: str
    reason: str | None
    currency: str = "USD"


@dataclass(frozen=True)
class V2Price:
    physical: PriceComponent
    unhedged: PriceComponent
    hedged: PriceComponent
    model_load: PriceComponent
    loaded: PriceComponent
    market: PriceComponent
    selection_asof: SelectionAsOfV2
    hedge_ratio: float | None


def payoff(values: np.ndarray, spec: V2Payoff) -> np.ndarray:
    """Adapt V2 ticket fields to the canonical portfolio payoff interpreter."""
    if spec.multiplier <= 0 or spec.strike < 0 or (spec.cap is not None and spec.cap < 0):
        raise ValueError("invalid V2 payoff parameters")
    if spec.kind == "linear":
        if spec.entry_level is None:
            raise ValueError("linear payoff requires entry_level")
        node = PayoffNode("index_linear", entry_level=spec.entry_level, multiplier=spec.multiplier)
    else:
        if spec.kind.startswith("capped") and spec.cap is None:
            raise ValueError("capped payoff requires a USD cap")
        node = PayoffNode(spec.kind, strike=spec.strike, multiplier=spec.multiplier, cap=spec.cap)
    return evaluate(node, values)


def select_asof(
    *,
    valuation_date: date,
    pair,
    contract_year: int | None,
    observation_cutoff: date,
    metadata_cutoff: date,
    decision_eligible: np.ndarray,
    prior_scores: np.ndarray,
    nearest_station: int,
    candidate_rankings: np.ndarray | None = None,
    station_ids: tuple[str, ...] | None = None,
) -> SelectionAsOfV2:
    """Make an explicit current decision from declared cutoffs and candidate inputs."""
    window = resolve_contract_window(pair, valuation_date, contract_year=contract_year)
    eligible = np.asarray(decision_eligible, dtype=bool)
    scores = np.asarray(prior_scores, dtype=float)
    if eligible.ndim != 1 or scores.shape != eligible.shape:
        raise ValueError(
            "current decision eligibility and scores must be one-dimensional station arrays"
        )
    decision = choose_policy(
        "prior_best",
        decision_eligible=eligible[None, None, :],
        prior_scores=scores[None, None, :],
        nearest_station=np.array([nearest_station]),
        candidate_rankings=None if candidate_rankings is None else candidate_rankings[None, :],
    )
    if station_ids is not None and len(station_ids) != eligible.size:
        raise ValueError("station_ids must align with current candidate inputs")
    return SelectionAsOfV2(
        valuation_date,
        window.contract_window_id,
        window.contract_year,
        observation_cutoff,
        metadata_cutoff,
        int(decision.choice[0, 0]),
        None
        if decision.choice[0, 0] < 0 or station_ids is None
        else station_ids[int(decision.choice[0, 0])],
        str(decision.reason[0, 0]),
    )


def _component(
    name: str, amount: float | None, method: str, reason: str | None = None
) -> PriceComponent:
    return PriceComponent(
        name, "available" if amount is not None else "unavailable", amount, method, reason
    )


def price_v2(
    *,
    payoff_spec: V2Payoff,
    county_paths: np.ndarray,
    station_paths: np.ndarray | None,
    selection_asof: SelectionAsOfV2,
    model_load: float | None = None,
    market_amount: float | None = None,
    market_reason: str = "no_market_observation",
    county_scenario_ids: tuple[str, ...] | None = None,
    station_scenario_ids: tuple[str, ...] | None = None,
    station_entity_ids: tuple[str, ...] | None = None,
) -> V2Price:
    """Return separate physical, unhedged, hedged and market components.

    A hedged result needs real finite, aligned station paths for the frozen
    selected station. There is deliberately no county-self or atlas-ratio
    substitute when they are absent.
    """
    county = np.asarray(county_paths, dtype=float).reshape(-1)
    if county.size == 0 or not np.isfinite(county).all():
        raise ValueError("county paths must be finite/nonempty")
    if model_load is not None and (not np.isfinite(model_load) or model_load < 0):
        raise ValueError("model_load must be finite and non-negative when supplied")
    physical_payout = payoff(county, payoff_spec)
    physical = _component(
        "physical_expected_payout", float(physical_payout.mean()), "common_aligned_paths"
    )
    unhedged = _component(
        "unhedged_expected_payout", float(physical_payout.mean()), "physical_no_station_hedge"
    )
    station_index = selection_asof.choice_station_index
    if station_index < 0:
        hedged, ratio = (
            _component("hedged_indication", None, "unavailable", selection_asof.reason),
            None,
        )
    elif station_paths is None:
        hedged, ratio = (
            _component("hedged_indication", None, "unavailable", "missing_aligned_station_paths"),
            None,
        )
    else:
        stations = np.asarray(station_paths, dtype=float)
        if (
            county_scenario_ids is None
            or station_scenario_ids is None
            or station_entity_ids is None
        ):
            raise ValueError("V2 hedged pricing requires scenario IDs and station entity IDs")
        if tuple(county_scenario_ids) != tuple(station_scenario_ids):
            raise ValueError("county and station scenario IDs must match exactly")
        if selection_asof.selected_station_id not in station_entity_ids:
            raise ValueError("selected station is absent from aligned station scenario matrix")
        station_index = station_entity_ids.index(selection_asof.selected_station_id)
        if (
            stations.ndim != 2
            or stations.shape[0] != county.size
            or station_index >= stations.shape[1]
        ):
            raise ValueError(
                "station_paths must be aligned (paths, stations) and contain selected station"
            )
        station = stations[:, station_index]
        if not np.isfinite(station).all():
            hedged, ratio = (
                _component(
                    "hedged_indication", None, "unavailable", "nonfinite_aligned_station_paths"
                ),
                None,
            )
        else:
            # This is payoff-specific: a nonlinear ticket gets a new covariance ratio.
            hedge_cashflow = payoff(
                station, V2Payoff("linear", multiplier=payoff_spec.multiplier, entry_level=0.0)
            )
            centered_hedge = hedge_cashflow - hedge_cashflow.mean()
            variance = float(centered_hedge @ centered_hedge)
            if variance <= max(
                np.finfo(float).eps, 1e-12 * max(float(hedge_cashflow @ hedge_cashflow), 1.0)
            ):
                hedged, ratio = (
                    _component(
                        "hedged_indication", None, "unavailable", "degenerate_station_payoff"
                    ),
                    None,
                )
            else:
                ratio = float(
                    ((physical_payout - physical_payout.mean()) @ centered_hedge) / variance
                )
                residual = physical_payout - ratio * centered_hedge
                # A zero-mean linear hedge changes residual risk, not the
                # physical expected customer payout.  Keep the transfer
                # assumption below as a distinct component instead of
                # silently folding it into a physical result.
                hedged = _component(
                    "hedged_indication",
                    float(residual.mean()),
                    "payoff_specific_aligned_station_hedge",
                )
    model_component = _component(
        "assumed_model_load",
        None if model_load is None else float(model_load),
        "declared_risk_transfer_assumption",
        "missing_model_load_assumption" if model_load is None else None,
    )
    loaded = _component(
        "loaded_indication",
        None if model_load is None else float(physical_payout.mean() + model_load),
        "physical_expected_payout_plus_declared_model_load",
        "missing_model_load_assumption" if model_load is None else None,
    )
    market = _component(
        "market_observation",
        market_amount,
        "market_observation",
        None if market_amount is not None else market_reason,
    )
    return V2Price(
        physical, unhedged, hedged, model_component, loaded, market, selection_asof, ratio
    )


def price_v2_legacy_arrays(**kwargs) -> V2Price:
    """Explicit compatibility-only array adapter; never use for a V2 public result."""
    kwargs.setdefault(
        "county_scenario_ids", tuple(str(i) for i in range(len(kwargs["county_paths"])))
    )
    station = kwargs.get("station_paths")
    if station is not None:
        kwargs.setdefault("station_scenario_ids", kwargs["county_scenario_ids"])
        selection = kwargs["selection_asof"]
        kwargs.setdefault(
            "station_entity_ids",
            tuple([selection.selected_station_id or "legacy"] * station.shape[1]),
        )
    return price_v2(**kwargs)
