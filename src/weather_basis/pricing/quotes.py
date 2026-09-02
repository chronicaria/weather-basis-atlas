"""Loaded actuarial option indications from aligned county/station draws.

Implements the decomposition prescribed by build-plan Section 8.3.  This
module accepts arrays only; orchestration is responsible for loading draws and
constructing the burn-bootstrap model load.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np


@dataclass(frozen=True)
class PayoffSpec:
    strike: float
    kind: Literal["call", "put"] = "call"
    multiplier: float = 20.0


@dataclass(frozen=True)
class JointDraws:
    county: np.ndarray
    station: np.ndarray | None


@dataclass(frozen=True)
class HedgeSpec:
    station: str
    station_model: str = "available"
    atlas_h: float | None = None


@dataclass(frozen=True)
class Quote:
    mid: float
    ask: float
    bid_raw: float
    bid: float
    no_bid: bool
    expected_payout: float
    residual_load_ask: float
    residual_load_bid: float
    model_load: float
    friction: float
    es_alpha: float
    h: float
    station: str
    station_model: str
    hedge_source: str


def _setting(cfg: Any, name: str, default: float) -> float:
    quotes = cfg.get("quotes", {}) if isinstance(cfg, dict) else getattr(cfg, "quotes", {})
    if isinstance(quotes, dict):
        return float(quotes.get(name, default))
    return float(getattr(quotes, name, default))


def _expected_shortfall(values: np.ndarray, alpha: float) -> float:
    n_tail = max(1, int(np.ceil((1.0 - alpha) * values.size)))
    return float(np.mean(np.partition(values, values.size - n_tail)[-n_tail:]))


def loaded_quote(
    x: PayoffSpec, joint: JointDraws, hedge: HedgeSpec, cfg: Any, lam_model: float
) -> Quote:
    """Compute a call or put loaded premium using one aligned joint simulation."""
    county = np.asarray(joint.county, dtype=np.float64).reshape(-1)
    if county.size == 0 or not np.isfinite(county).all():
        raise ValueError("county draws must be a non-empty finite vector")
    if x.multiplier <= 0 or x.strike < 0 or x.kind not in {"call", "put"}:
        raise ValueError("invalid payoff specification")
    if lam_model < 0:
        raise ValueError("model load must be non-negative")
    multiplier = float(x.multiplier)
    payoff = multiplier * (
        np.maximum(county - x.strike, 0.0)
        if x.kind == "call"
        else np.maximum(x.strike - county, 0.0)
    )
    station = (
        None if joint.station is None else np.asarray(joint.station, dtype=np.float64).reshape(-1)
    )
    use_station = hedge.station_model != "unavailable" and station is not None
    if use_station:
        if station.size != county.size or not np.isfinite(station).all():
            raise ValueError("station draws must be finite and aligned with county draws")
        futures_payoff = multiplier * station
        variance = float(np.mean((futures_payoff - futures_payoff.mean()) ** 2))
        h = (
            0.0
            if variance == 0.0
            else float(
                np.mean((payoff - payoff.mean()) * (futures_payoff - futures_payoff.mean()))
                / variance
            )
        )
        residual = payoff - h * (futures_payoff - futures_payoff.mean())
        hedge_source = "joint_station"
    else:
        # D-71's fallback is deliberately not an unhedged quote.  A station
        # without a daily model cannot supply aligned station paths, so the
        # registered approximation applies the historical atlas ratio to the
        # county's own simulated futures innovation.  This keeps the stated
        # ratio, residual load, and friction internally consistent while
        # retaining an explicit machine-readable warning for the UI.
        atlas_h = hedge.atlas_h
        h = 0.0 if atlas_h is None or not np.isfinite(atlas_h) else float(atlas_h)
        county_futures = multiplier * county
        residual = payoff - h * (county_futures - county_futures.mean())
        hedge_source = "atlas_county_fallback"
    mid = float(payoff.mean())
    alpha = _setting(cfg, "alpha", 0.95)
    weight = _setting(cfg, "w", 0.5)
    tick = _setting(cfg, "friction_ticks", 1.0)
    if not 0.0 < alpha < 1.0 or weight < 0.0 or tick < 0.0:
        raise ValueError("invalid quote configuration")
    es_upper = _expected_shortfall(residual, alpha)
    es_lower_neg = _expected_shortfall(-residual, alpha)
    residual_load_ask = max(0.0, weight * (es_upper - mid))
    residual_load_bid = max(0.0, weight * (es_lower_neg + mid))
    model_load = float(lam_model)
    friction = abs(h) * multiplier * tick
    ask = mid + residual_load_ask + model_load + friction
    bid_raw = mid - residual_load_bid - model_load - friction
    return Quote(
        mid=mid,
        ask=ask,
        bid_raw=bid_raw,
        bid=max(0.0, bid_raw),
        no_bid=bid_raw <= 0.0,
        expected_payout=mid,
        residual_load_ask=residual_load_ask,
        residual_load_bid=residual_load_bid,
        model_load=model_load,
        friction=friction,
        es_alpha=alpha,
        h=h,
        station=hedge.station,
        station_model=hedge.station_model,
        hedge_source=hedge_source,
    )
