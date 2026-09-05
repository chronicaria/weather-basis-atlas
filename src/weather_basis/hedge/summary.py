"""Origin-clustered R01 intervals and selection stability from frozen panels."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def summarize_r01(r01_dir: Path, *, block_length: int = 5) -> pd.DataFrame:
    """Use contiguous origin blocks; no county/path independence assumption."""
    comparison = pd.read_parquet(r01_dir / "matched_comparisons.parquet").set_index(
        ["pair", "fips"]
    )
    rows = []
    for path in sorted((r01_dir / "policy_evaluations").glob("*.parquet")):
        frame = pd.read_parquet(path)
        pair = path.stem
        choices = pd.read_parquet(r01_dir / "policy_decisions" / path.name)
        for fips, group in frame.groupby("fips", sort=False):
            wide = group.pivot(index="season", columns="policy", values="residual").sort_index()
            common = wide.dropna(subset=["prior_best", "nearest_eligible"])
            item = comparison.loc[(pair, str(fips))]
            delta = float(item.he_prior_best - item.he_nearest) if item.reason == "ok" else np.nan
            loss = (common.nearest_eligible**2 - common.prior_best**2).to_numpy()
            blocks = np.array(
                [x.mean() for x in np.array_split(loss, max(1, len(loss) // block_length))]
            )
            se = (
                float(blocks.std(ddof=1) / np.sqrt(len(blocks)) * len(loss) / item.denominator)
                if len(blocks) > 1 and item.denominator > 0
                else np.nan
            )
            chosen = choices.loc[
                (choices.fips == fips) & (choices.policy == "prior_best"), "choice_station_index"
            ]
            selected = chosen[chosen >= 0].to_numpy()
            stability = (
                float(np.bincount(selected).max() / len(selected)) if len(selected) else np.nan
            )
            rows.append(
                {
                    "pair": pair,
                    "fips": str(fips),
                    "delta_he": delta,
                    "interval_low": delta - 1.96 * se if np.isfinite(se) else np.nan,
                    "interval_high": delta + 1.96 * se if np.isfinite(se) else np.nan,
                    "interval_method": (
                        "paired-contiguous-origin-block-normal95-fixed-target-denominator"
                    ),
                    "block_length": block_length,
                    "n_blocks": len(blocks),
                    "selection_stability": stability,
                }
            )
    result = pd.DataFrame(rows)
    result.to_parquet(r01_dir / "r01_uncertainty_stability.parquet", index=False)
    return result
