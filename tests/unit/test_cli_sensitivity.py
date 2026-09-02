"""Plan Section 7.7: tournament CLI runs both registered sensitivity artefacts."""

from __future__ import annotations

import shutil
from pathlib import Path

from weather_basis import cli
from weather_basis.models import run as model_run
from weather_basis.models import sensitivity
from weather_basis.validation import atlas_sensitivity


def test_models_tournament_wires_sensitivity_outputs(tmp_path: Path, monkeypatch) -> None:
    """Section 7.7: normal tournament/reproduction path cannot omit sensitivities."""
    (tmp_path / "config").mkdir()
    shutil.copy(Path("config/defaults.yaml"), tmp_path / "config/defaults.yaml")
    calls: list[str] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        model_run, "run_tournament", lambda root, cfg: calls.append("tournament") or {}
    )
    monkeypatch.setattr(
        sensitivity,
        "run_sensitivities",
        lambda root, cfg: (
            calls.append("daily") or root / "results/tournament/sensitivities.parquet"
        ),
    )
    monkeypatch.setattr(
        atlas_sensitivity,
        "run_atlas_anomaly_sensitivity",
        lambda root: (
            calls.append("atlas") or root / "results/tournament/atlas_anomaly_sensitivities.parquet"
        ),
    )
    monkeypatch.setattr(
        "weather_basis.manifest_stage.write_sensitivity_manifest",
        lambda *args, **kwargs: calls.append("manifest"),
    )
    monkeypatch.setattr(
        cli, "_write_stage", lambda *args, **kwargs: calls.append("tournament_manifest")
    )
    assert cli.main(["models", "tournament"]) == 0
    assert calls == ["tournament", "daily", "atlas", "manifest", "tournament_manifest"]
