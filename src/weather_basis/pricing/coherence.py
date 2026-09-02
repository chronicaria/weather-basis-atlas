"""Reusable Section 8.4 quote-coherence checks.

The functions return structured counts rather than raising, so a full quote
build can write useful diagnostics while its gate simply tests ``report.ok``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

from weather_basis.pricing.distribution import SortedSamples
from weather_basis.pricing.quotes import Quote


@dataclass
class CoherenceReport:
    violations: dict[str, int] = field(default_factory=dict)
    diagnostics: dict[str, float | int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(self.violations.values())

    def add(self, name: str, failed: np.ndarray | bool | int) -> None:
        count = int(np.count_nonzero(failed))
        if count:
            self.violations[name] = self.violations.get(name, 0) + count

    def merge(self, other: CoherenceReport) -> CoherenceReport:
        for name, count in other.violations.items():
            self.violations[name] = self.violations.get(name, 0) + count
        for name, value in other.diagnostics.items():
            self.diagnostics[name] = value
        return self


def check_distribution(samples: SortedSamples, strikes: np.ndarray, m: float) -> CoherenceReport:
    """Check bounds, monotonicity, convexity, and put-call parity for mids."""
    report = CoherenceReport()
    k = np.asarray(strikes, dtype=np.float64).reshape(-1)
    if k.size == 0 or np.any(~np.isfinite(k)):
        raise ValueError("strikes must be a non-empty finite vector")
    order = np.argsort(k, kind="stable")
    k = k[order]
    call = np.asarray(samples.call(k, m), dtype=np.float64)
    put = np.asarray(samples.put(k, m), dtype=np.float64)
    mean = samples.mean()
    scale = max(1.0, abs(float(m)) * max(1.0, abs(mean), float(np.max(k))))
    tolerance = 1e-11 * scale
    report.add("call_bounds", (call < -tolerance) | (call > float(m) * mean + tolerance))
    report.add("call_jensen", call + tolerance < float(m) * np.maximum(mean - k, 0.0))
    report.add("put_bounds", (put < -tolerance) | (put > float(m) * k + tolerance))
    report.add("call_monotonicity", np.diff(call) > tolerance)
    report.add("put_monotonicity", np.diff(put) < -tolerance)
    if k.size >= 3:
        # Slopes, rather than raw equally-spaced second differences, work for
        # arbitrary explorer grids as well as the required 41-point grid.
        # Calls are evaluated from float32 samples; do not infer a shape
        # violation from slopes between numerically indistinguishable strikes.
        min_width = 1e-6 * max(1.0, float(np.max(np.abs(k))), float(np.max(abs(samples.values))))
        keep = np.r_[True, np.diff(k) > min_width]
        k_shape, call_shape = k[keep], call[keep]
        widths = np.diff(k_shape)
        slopes = np.diff(call_shape) / widths
        if slopes.size >= 2:
            slope_tolerance = max(
                tolerance, 1e-7 * max(1.0, abs(float(m)), float(np.max(abs(slopes))))
            )
            report.add("call_convexity", np.diff(slopes) < -slope_tolerance)
    parity_tol = 1e-9 * max(1.0, abs(float(m) * mean))
    report.add("mid_parity", np.abs(call - put - float(m) * (mean - k)) > parity_tol)
    return report


def check_quote(quote: Quote, *, tolerance: float = 1e-9) -> CoherenceReport:
    """Check the gated ordering, non-negativity, and load identity for a quote."""
    report = CoherenceReport()
    report.add(
        "quote_order", quote.bid > quote.mid + tolerance or quote.mid > quote.ask + tolerance
    )
    report.add("negative_bid", quote.bid < -tolerance)
    report.add("negative_ask_load", quote.residual_load_ask < -tolerance)
    report.add("negative_bid_load", quote.residual_load_bid < -tolerance)
    identity = quote.ask - quote.bid_raw - (
        quote.residual_load_ask
        + quote.residual_load_bid
        + 2.0 * quote.model_load
        + 2.0 * quote.friction
    )
    report.add("load_identity", abs(identity) > tolerance)
    return report


def check_quotes(quotes: Iterable[Quote], *, tolerance: float = 1e-9) -> CoherenceReport:
    """Aggregate :func:`check_quote` over a table/build."""
    report = CoherenceReport()
    for quote in quotes:
        report.merge(check_quote(quote, tolerance=tolerance))
    return report


def check_seed_agreement(
    mid_a: np.ndarray,
    mid_b: np.ndarray,
    se_a: np.ndarray,
    se_b: np.ndarray,
    *,
    sigma: float = 4.0,
    ask_a: np.ndarray | None = None,
    ask_b: np.ndarray | None = None,
    ask_se_a: np.ndarray | None = None,
    ask_se_b: np.ndarray | None = None,
) -> CoherenceReport:
    """Check the Section 8.4 independent-seed Monte-Carlo agreement bound."""
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    report = CoherenceReport()
    a, b, sea, seb = np.broadcast_arrays(mid_a, mid_b, se_a, se_b)
    report.add("seed_mid_agreement", np.abs(a - b) > sigma * np.sqrt(sea**2 + seb**2))
    ask_args = (ask_a, ask_b, ask_se_a, ask_se_b)
    if any(item is not None for item in ask_args):
        if any(item is None for item in ask_args):
            raise ValueError("provide all ask values and bootstrap standard errors")
        aa, ab, ase_a, ase_b = np.broadcast_arrays(ask_a, ask_b, ask_se_a, ask_se_b)
        report.add("seed_ask_agreement", np.abs(aa - ab) > sigma * np.sqrt(ase_a**2 + ase_b**2))
    return report


def diagnostics_for_asks(
    strikes: np.ndarray, asks: np.ndarray, *, tolerance: float = 0.0
) -> dict[str, int]:
    """Return non-gating ask-shape diagnostics required in ``coherence.json``."""
    k = np.asarray(strikes, dtype=np.float64).reshape(-1)
    a = np.asarray(asks, dtype=np.float64).reshape(-1)
    if k.size != a.size:
        raise ValueError("strikes and asks must have equal length")
    order = np.argsort(k, kind="stable")
    k, a = k[order], a[order]
    increasing = int(np.count_nonzero(np.diff(a) > tolerance))
    min_width = 1e-6 * max(1.0, float(np.max(np.abs(k))))
    keep = np.r_[True, np.diff(k) > min_width]
    k, a = k[keep], a[keep]
    slopes = np.diff(a) / np.diff(k)
    nonconvex = int(np.count_nonzero(np.diff(slopes) < -tolerance)) if slopes.size > 1 else 0
    return {"ask_increasing": increasing, "ask_nonconvex": nonconvex}
