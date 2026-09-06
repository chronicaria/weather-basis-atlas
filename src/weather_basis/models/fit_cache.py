"""Exact-cutoff immutable daily-fit cache; never keyed by a contract label alone."""

from __future__ import annotations

import os
import platform
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_basis.models.daily import DailyFit
from weather_basis.models.residual import ARFit, LogVarFit
from weather_basis.provenance.ids import canonical_json, content_id


@dataclass(frozen=True)
class FitRequest:
    """All scientific/numerical support that may make a daily fit differ."""

    cutoff: str
    panel_id: str
    series_ids: tuple[str, ...]
    support_hash: str
    model_spec: dict[str, Any]
    producer_fingerprint: str
    numerical_environment: dict[str, str]
    schema_version: str = "2.0"

    def __post_init__(self) -> None:
        timestamp = pd.Timestamp(self.cutoff)
        if timestamp.tz is not None or timestamp != timestamp.normalize():
            raise ValueError("fit cutoff must be an exact timezone-naive calendar day")
        if not self.series_ids or len(set(self.series_ids)) != len(self.series_ids):
            raise ValueError("fit request requires unique ordered series IDs")

    @property
    def fit_id(self) -> str:
        return content_id(asdict(self))


def numerical_environment() -> dict[str, str]:
    """Record library/architecture evidence without using it as a worker setting."""

    return {
        "numpy": np.__version__,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


class FitCache:
    """Disk cache whose artifacts are valid only for exactly matching FitRequest."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def directory(self, request: FitRequest) -> Path:
        return self.root / request.fit_id.replace(":", "-")

    def load(self, request: FitRequest) -> DailyFit | None:
        directory = self.directory(request)
        metadata = directory / "request.json"
        arrays = directory / "fit.npz"
        if not metadata.is_file() or not arrays.is_file():
            return None
        if metadata.read_text(encoding="utf-8") != canonical_json(asdict(request)) + "\n":
            return None
        with np.load(arrays, allow_pickle=False) as archive:
            return DailyFit(
                mean_coef=archive["mean_coef"],
                ar=ARFit(
                    coef=archive["ar_coef"],
                    order=archive["ar_order"],
                    bic=archive["ar_bic"],
                    innovations=archive["ar_innovations"],
                    valid=archive["ar_valid"],
                ),
                logvar=LogVarFit(
                    coef=archive["logvar_coef"],
                    scale=archive["logvar_scale"],
                    harmonics=int(archive["logvar_harmonics"]),
                ),
                z=archive["z"],
                fit_mask=archive["fit_mask"],
            )

    def store(self, request: FitRequest, fit: DailyFit) -> Path:
        """Atomically publish a complete cache entry; existing IDs are immutable."""

        target = self.directory(request)
        if self.load(request) is not None:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        try:
            np.savez(
                staging / "fit.npz",
                mean_coef=fit.mean_coef,
                ar_coef=fit.ar.coef,
                ar_order=fit.ar.order,
                ar_bic=fit.ar.bic,
                ar_innovations=fit.ar.innovations,
                ar_valid=fit.ar.valid,
                logvar_coef=fit.logvar.coef,
                logvar_scale=fit.logvar.scale,
                logvar_harmonics=np.asarray(fit.logvar.harmonics),
                z=fit.z,
                fit_mask=fit.fit_mask,
            )
            (staging / "request.json").write_text(
                canonical_json(asdict(request)) + "\n", encoding="utf-8"
            )
            try:
                os.replace(staging, target)
            except FileExistsError:
                # Another deterministic worker won the same exact request.
                if self.load(request) is None:
                    raise
        finally:
            if staging.exists():
                for item in staging.iterdir():
                    item.unlink()
                staging.rmdir()
        return target

    def get_or_fit(self, request: FitRequest, factory: Any) -> tuple[DailyFit, bool]:
        cached = self.load(request)
        if cached is not None:
            return cached, True
        fit = factory()
        self.store(request, fit)
        return fit, False
