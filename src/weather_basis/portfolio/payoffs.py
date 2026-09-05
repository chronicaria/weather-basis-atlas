"""Closed long-unit V2 temperature payoff primitives; direction belongs to positions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class PayoffNode:
    """Closed declarative payoff node; direction/premium remain outside this long-unit payoff."""

    kind: Literal["index_linear", "call", "put", "capped_call", "capped_put", "sum", "scale"]
    strike: float | None = None
    entry_level: float | None = None
    multiplier: float = 1.0
    cap: float | None = None
    scale: float = 1.0
    children: tuple[PayoffNode, ...] = ()


def evaluate(node: PayoffNode, index: np.ndarray | float) -> np.ndarray:
    """Interpret the closed V2 payoff DSL without executing user expressions."""
    if node.kind == "index_linear":
        if node.entry_level is None:
            raise ValueError("linear payoff requires entry_level")
        return linear(index, node.entry_level, node.multiplier)
    if node.kind in {"call", "capped_call", "put", "capped_put"}:
        if node.strike is None:
            raise ValueError("option payoff requires strike")
        cap = node.cap if node.kind.startswith("capped_") else None
        return (
            call(index, node.strike, node.multiplier, cap)
            if "call" in node.kind
            else put(index, node.strike, node.multiplier, cap)
        )
    if node.kind == "sum":
        if not node.children:
            raise ValueError("sum payoff requires component nodes")
        return sum(
            (evaluate(child, index) for child in node.children), np.zeros_like(_index(index))
        )
    if node.kind == "scale":
        if len(node.children) != 1:
            raise ValueError("scale payoff requires exactly one component")
        return node.scale * evaluate(node.children[0], index)
    raise ValueError("unsupported payoff node")


def _index(values: np.ndarray | float) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if not np.isfinite(result).all():
        raise ValueError("index values must be finite")
    return result


def linear(index: np.ndarray | float, entry_level: float, multiplier: float = 1.0) -> np.ndarray:
    if multiplier < 0:
        raise ValueError("multiplier must be non-negative")
    return multiplier * (_index(index) - entry_level)


def call(
    index: np.ndarray | float, strike: float, multiplier: float = 1.0, cap: float | None = None
) -> np.ndarray:
    if multiplier < 0 or cap is not None and cap < 0:
        raise ValueError("multiplier and cap must be non-negative")
    result = multiplier * np.maximum(_index(index) - strike, 0.0)
    return result if cap is None else np.minimum(result, cap)


def put(
    index: np.ndarray | float, strike: float, multiplier: float = 1.0, cap: float | None = None
) -> np.ndarray:
    if multiplier < 0 or cap is not None and cap < 0:
        raise ValueError("multiplier and cap must be non-negative")
    result = multiplier * np.maximum(strike - _index(index), 0.0)
    return result if cap is None else np.minimum(result, cap)


def call_spread(
    index: np.ndarray | float, low_strike: float, high_strike: float, multiplier: float = 1.0
) -> np.ndarray:
    if high_strike < low_strike:
        raise ValueError("spread strikes are reversed")
    return call(index, low_strike, multiplier) - call(index, high_strike, multiplier)


def put_spread(
    index: np.ndarray | float, high_strike: float, low_strike: float, multiplier: float = 1.0
) -> np.ndarray:
    if high_strike < low_strike:
        raise ValueError("spread strikes are reversed")
    return put(index, high_strike, multiplier) - put(index, low_strike, multiplier)


def collar(
    index: np.ndarray | float, put_strike: float, call_strike: float, multiplier: float = 1.0
) -> np.ndarray:
    """Long put plus short call, before separately recorded premiums and fees."""
    return put(index, put_strike, multiplier) - call(index, call_strike, multiplier)
