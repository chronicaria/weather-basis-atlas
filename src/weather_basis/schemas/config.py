from __future__ import annotations

from dataclasses import dataclass

from .base import StrictRecord, require, validate_fips


@dataclass(frozen=True, kw_only=True)
class ResearchConfig(StrictRecord):
    name: str = "weather-basis-atlas-v2"
    seed: int = 20260905
    seed_schema_version: str = "v2-seed-1"
    county_universe: str = "CONUS-3107-v1"
    station_universe: str = "listed-reference-13-v1"
    pairs: tuple[str, ...] = (
        "HDD-01",
        "HDD-02",
        "HDD-03",
        "HDD-04",
        "HDD-10",
        "HDD-11",
        "HDD-12",
        "CDD-04",
        "CDD-05",
        "CDD-06",
        "CDD-07",
        "CDD-08",
        "CDD-09",
        "CDD-10",
    )
    first_test_year: int = 1981
    last_test_year: int = 2025
    training_window: int = 30
    min_train: int = 15
    valuation_asof: str = "2026-07-01"
    horizon_start: str = "2026-07-01"
    horizon_end: str = "2027-06-30"
    scenario_generator: str = "common-year-trend-bootstrap-v1"
    offline_paths: int = 10000
    public_paths: int = 2000
    tail_level: float = 0.90
    equivalence_bands: tuple[float, ...] = (0.0, 0.02, 0.05)
    loss_convention: str = "positive_loss_minus_long_payoff_plus_cost-v1"
    he_convention: str = "replication-mse-common-centered-target-v2"
    currency: str = "USD"
    numerical_tolerance: float = 1e-8

    def __post_init__(self):
        super().__post_init__()
        require(self.currency == "USD", "Core supports USD only")
        require(0 < self.tail_level < 1, "tail_level must be in (0,1)")
        require(0 < self.public_paths <= self.offline_paths, "Invalid scenario counts")
        require(self.training_window >= self.min_train > 1, "Invalid training support")
        require(len(set(self.pairs)) == len(self.pairs), "Duplicate pairs")
        for pair in self.pairs:
            kind, month = pair.split("-")
            require(kind in ("HDD", "CDD") and 1 <= int(month) <= 12, "Invalid pair")
        require(
            self.loss_convention == "positive_loss_minus_long_payoff_plus_cost-v1",
            "Unsupported loss convention",
        )
        require(
            self.he_convention == "replication-mse-common-centered-target-v2",
            "Unsupported HE convention",
        )


@dataclass(frozen=True, kw_only=True)
class ExecutionProfile(StrictRecord):
    name: str = "fixture"
    workers: int = 1
    memory_gib: float = 12.0
    cache_dir: str = "var/cache/v2"
    scratch_dir: str = "var/shards/v2"
    chunk_counties: int = 64
    blas_threads: int = 1
    telemetry: bool = True

    def __post_init__(self):
        super().__post_init__()
        require(1 <= self.workers <= 4, "workers must be between 1 and 4 after profiling")
        require(self.memory_gib > 0 and self.chunk_counties > 0, "Invalid execution budget")
        require(self.blas_threads == 1, "V2 parallel profile requires one BLAS thread")


@dataclass(frozen=True, kw_only=True)
class PresentationPolicy(StrictRecord):
    max_locations: int = 6
    max_exposure_rows: int = 24
    max_hedge_columns: int = 39
    max_horizon_months: int = 12
    default_fips: str = "31109"
    default_pair: str = "HDD-01"
    default_route: str = "explore"
    money_decimals: int = 2

    def __post_init__(self):
        super().__post_init__()
        validate_fips(self.default_fips)


@dataclass(frozen=True, kw_only=True)
class RunRequest(StrictRecord):
    stage: str
    mode: str = "fixture"
    pairs: tuple[str, ...] = ()
    origins: tuple[int, ...] = ()
    county_panel: tuple[str, ...] = ()
    book_path: str | None = None
    objective: str = "es"

    def __post_init__(self):
        super().__post_init__()
        require(self.mode in ("fixture", "representative", "full"), "Unknown request mode")
        for fips in self.county_panel:
            validate_fips(fips)
