"""Release-wide source-season plan, computed once before county chunk loading."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from weather_basis.provenance.ids import content_id

from .common import CommonScenarioPlan, _annual_windows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class GlobalSeasonPlan:
    """Frozen annual source rows; public paths are the offline-plan prefix."""

    common_plan: CommonScenarioPlan
    location_ids: tuple[str, ...]
    eligible_seasons: tuple[int, ...]
    sampled_seasons_offline: tuple[int, ...]
    source_hashes: tuple[tuple[str, str], ...]
    cutoff: str

    @property
    def plan_id(self) -> str:
        return content_id(
            {
                "common_plan_id": self.common_plan.plan_id,
                "location_ids": self.location_ids,
                "eligible_seasons": self.eligible_seasons,
                "sampled_seasons_offline": self.sampled_seasons_offline,
                "source_hashes": self.source_hashes,
                "cutoff": self.cutoff,
            }
        )

    def public_seasons(self, count: int) -> tuple[int, ...]:
        if count < 1 or count > len(self.sampled_seasons_offline):
            raise ValueError("public paths must be a nonempty prefix of offline paths")
        return self.sampled_seasons_offline[:count]


def build_global_season_plan(
    root: Path | str,
    *,
    offline_paths: int = 10_000,
    valuation_asof: str = "2026-07-01",
    seed: int = 20260905,
    horizon_start: str = "2026-07-01",
    horizon_end: str = "2027-06-30",
) -> GlobalSeasonPlan:
    """Memory-map the declared national panel and find complete pre-cutoff seasons.

    The finite scan is by one season (at most 366 days), never by a national
    scenario cube.  Its output is independent of any subsequently loaded
    county chunk.
    """
    root = Path(root)
    panel = root / "data" / "panel"
    dates = pd.DatetimeIndex(np.load(panel / "dates.npy", mmap_mode="r", allow_pickle=False))
    counties = np.load(panel / "fips.npy", mmap_mode="r", allow_pickle=False).astype("U")
    stations = np.load(panel / "station_ids.npy", mmap_mode="r", allow_pickle=False).astype("U")
    county_values = np.load(panel / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)
    station_values = np.load(panel / "stations_tbar_f32.npy", mmap_mode="r", allow_pickle=False)
    if (horizon_start, horizon_end) != ("2026-07-01", "2027-06-30"):
        raise ValueError("only the registered 2026-07 through 2027-06 horizon is supported")
    target = pd.date_range(horizon_start, horizon_end, freq="D")
    cutoff = pd.Timestamp(valuation_asof)
    eligible: list[int] = []
    for season, rows in _annual_windows(dates).items():
        if len(rows) != len(target) or not np.all(dates[rows] < cutoff):
            continue
        if tuple(dates[rows].strftime("%m-%d")) != tuple(target.strftime("%m-%d")):
            continue
        if np.all(np.isfinite(county_values[rows])) and np.all(np.isfinite(station_values[rows])):
            eligible.append(season)
    if not eligible:
        raise ValueError("national declared universe has no complete pre-cutoff common seasons")
    location_ids = tuple(str(item) for item in counties) + tuple(str(item) for item in stations)
    universe = content_id({"location_ids": location_ids, "eligible_seasons": eligible})
    common = CommonScenarioPlan(
        valuation_asof=valuation_asof,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        scenario_count=offline_paths,
        seed=seed,
        location_universe_id=universe,
    )
    rng = np.random.default_rng(seed)
    sampled = tuple(int(item) for item in rng.choice(eligible, size=offline_paths, replace=True))
    sources = tuple(
        (name, _sha256(panel / name))
        for name in (
            "dates.npy",
            "fips.npy",
            "station_ids.npy",
            "tavg_f32.npy",
            "stations_tbar_f32.npy",
        )
    )
    return GlobalSeasonPlan(
        common_plan=common,
        location_ids=location_ids,
        eligible_seasons=tuple(eligible),
        sampled_seasons_offline=sampled,
        source_hashes=sources,
        cutoff=valuation_asof,
    )
