#!/usr/bin/env python3
"""Small RSS benchmark for the streaming simulator (plan Section 7.4)."""

from __future__ import annotations

import argparse
import resource
import sys

import numpy as np

from weather_basis.models.simulate import block_plan, simulate_month


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-rss-gb", type=float, default=12.0)
    parser.add_argument("--M", type=int, default=2000)
    parser.add_argument("--series", type=int, default=200)
    args = parser.parse_args()
    rng = np.random.default_rng(20260901)
    days, hist = 61, 2700
    plan = block_plan(rng, M=args.M, n_days=days, mean_block=7, candidate_days=np.arange(hist))
    simulate_month(
        rng.normal(size=(hist, args.series)).astype(np.float32),
        plan=plan,
        sigma=np.ones((days, args.series)),
        ar=np.zeros((args.series, 5)),
        mean=np.full((days, args.series), 65.0),
        init_state=None,
        series_slice=slice(None),
        accumulate_mask=np.ones(days, dtype=bool),
        index_fn=lambda t: np.maximum(65.0 - t, 0.0),
    )
    # macOS reports bytes; Linux reports KiB.
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss if sys.platform == "darwin" else rss * 1024
    total_gb = rss_bytes * args.workers / 1024**3
    print(f"per-worker RSS={rss_bytes / 1024**2:.1f} MiB; workers×RSS={total_gb:.2f} GiB")
    if total_gb >= args.max_rss_gb:
        raise SystemExit("RSS budget exceeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
