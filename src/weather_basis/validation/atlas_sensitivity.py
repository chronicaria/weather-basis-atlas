"""Atlas anomaly sensitivity behind the Section 2.1 validation boundary."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.contracts.calendar import PAIRS, Pair
from weather_basis.hedge.atlas import _metrics
from weather_basis.hedge.rolling import rolling_residuals
from weather_basis.models.sensitivity import _subset


def _trend_anomaly(index: np.ndarray, seasons: np.ndarray, min_prior: int) -> np.ndarray:
    """Return pre-season trailing-30 linear-trend anomalies without look-ahead."""
    values = np.asarray(index, dtype=float)
    out = np.full_like(values, np.nan)
    for column in range(values.shape[1]):
        for row in range(values.shape[0]):
            earlier = np.flatnonzero(np.isfinite(values[:row, column]))[-30:]
            if earlier.size < min_prior or not np.isfinite(values[row, column]):
                continue
            beta = np.polyfit(seasons[earlier], values[earlier, column], 1)
            out[row, column] = values[row, column] - np.polyval(beta, seasons[row])
    return out


def _panel(
    root: Path, pair: Pair, fips: np.ndarray, stations: np.ndarray
) -> tuple[np.ndarray, ...]:
    county = pd.read_parquet(root / "results" / "indices" / f"county_{pair.key}.parquet")
    station = pd.read_parquet(root / "results" / "indices" / f"station_{pair.key}.parquet")
    years = np.intersect1d(county.season.unique(), station.season.unique()).astype(int)

    def matrix(frame: pd.DataFrame, key: str, ids: np.ndarray, field: str) -> np.ndarray:
        return (
            frame.pivot(index="season", columns=key, values=field)
            .reindex(index=years, columns=ids)
            .to_numpy(dtype=float)
        )

    return (
        years,
        matrix(county, "fips", fips, "index"),
        matrix(station, "ghcnd_id", stations, "index"),
        matrix(county, "fips", fips, "anomaly"),
        matrix(station, "ghcnd_id", stations, "anomaly"),
    )


def run_atlas_anomaly_sensitivity(root: Path) -> Path:
    """Write 18-county trailing-normal versus trend-anomaly pooled-HE table.

    This is a separate clearly named Section 7.7 artefact because the models
    package is deliberately forbidden from importing hedge implementation.
    """
    root = Path(root)
    _, fips = _subset(root)
    stations = pd.read_csv(
        root / "data/metadata/station_registry.csv", dtype={"ghcnd_id": str}
    ).ghcnd_id.to_numpy(dtype="U")
    rows: list[dict[str, object]] = []
    for pair in PAIRS:
        years, county_index, station_index, county_normal, station_normal = _panel(
            root, pair, fips, stations
        )
        variants = {
            "trailing_normal": (county_normal, station_normal),
            "trend_anomaly": (
                _trend_anomaly(county_index, years, 15),
                _trend_anomaly(station_index, years, 10),
            ),
        }
        values: dict[str, np.ndarray] = {}
        first = int(np.searchsorted(years, 1981))
        for name, (county_anomaly, station_anomaly) in variants.items():
            rolling = rolling_residuals(
                county_anomaly, station_anomaly, first_test=first, min_train=np.full(18, 10)
            )
            values[name] = np.asarray(
                [
                    _metrics(rolling.resid[:, c, c], county_anomaly[first:, c], years[first:])["he"]
                    for c in range(18)
                ],
                dtype=float,
            )
        for c, fips_value in enumerate(fips):
            baseline = values["trailing_normal"][c]
            for code, name in enumerate(("trailing_normal", "trend_anomaly")):
                score = values[name][c]
                rows.append(
                    {
                        "dimension": "atlas_anomaly_method",
                        "value": code,
                        "variant_label": name,
                        "pair": pair.key,
                        "fips": str(fips_value),
                        "metric": "he_pooled",
                        "metric_value": score,
                        "baseline_value": baseline,
                        "difference_vs_baseline": score - baseline,
                        "baseline_label": "trailing 30-season normal (atlas baseline)",
                    }
                )
    output = root / "results" / "tournament" / "atlas_anomaly_sensitivities.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["value", "pair", "fips"], kind="stable").to_parquet(
        output, index=False
    )
    return output
