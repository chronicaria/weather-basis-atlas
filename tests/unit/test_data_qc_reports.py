"""Focused unit checks for build-plan Sections 4.3, 4.5, 4.6, and 4.7 QC outputs."""

from __future__ import annotations

import json
from argparse import Namespace

import numpy as np
import pandas as pd
import pytest

from weather_basis.ingest.geography import write_geography_population_manifests
from weather_basis.ingest.ghcnd import backfill_station_registry
from weather_basis.ingest.qc import _write_panel_consistency, _write_panel_tavg
from weather_basis.io import sha256, write_parquet


def test_registry_first_complete_month_is_derived_from_station_qc(tmp_path) -> None:
    """Section 4.5: registry usability dates are derived from monthly QC, not typed by hand."""

    (tmp_path / "data/metadata").mkdir(parents=True)
    (tmp_path / "data/panel").mkdir(parents=True)
    (tmp_path / "data/metadata/station_registry.csv").write_text(
        "ghcnd_id,first_complete_month\nUSW00000001,\nUSW00000002,\n", encoding="utf-8"
    )
    write_parquet(
        pd.DataFrame(
            {
                "ghcnd_id": ["USW00000001", "USW00000001", "USW00000002"],
                "year": [1951, 1951, 1960],
                "month": [2, 1, 3],
                "qc_status": ["complete", "excluded", "gap_filled"],
            }
        ),
        tmp_path / "data/panel/station_qc.parquet",
    )
    actual = backfill_station_registry(tmp_path)
    assert actual.first_complete_month.tolist() == ["1951-02", "1960-03"]
    assert "1951-02" in (tmp_path / "data/metadata/station_registry.csv").read_text()


def test_qc_panel_reports_include_registered_spot_checks_and_common_window(tmp_path) -> None:
    """Section 4.3: panel QC reports expose fixed shape/range and TAVG identity evidence."""

    qc = tmp_path / "results/qc"
    qc.mkdir(parents=True)
    root = tmp_path
    (root / "data/panel").mkdir(parents=True)
    dates = np.array(["2021-02-01", "2023-01-01"], dtype="datetime64[D]")
    tavg = np.array([[[-27.3]], [[50.0]]], dtype=np.float32).reshape(2, 1)
    tmax = np.array([[-20.0], [60.0]], dtype=np.float32)
    tmin = np.array([[-34.6], [40.0]], dtype=np.float32)
    np.save(root / "data/panel/tmax_f32.npy", tmax)
    np.save(root / "data/panel/tmin_f32.npy", tmin)
    _write_panel_tavg(qc / "panel_tavg.json", dates, tavg)
    _write_panel_consistency(root, qc, dates, tavg)
    panel = json.loads((qc / "panel_tavg.json").read_text())
    consistency = json.loads((qc / "panel_consistency.json").read_text())
    assert panel["january_2023_county_days"] == 1
    assert panel["february_2021_minimum_f"] == pytest.approx(-27.3)
    assert panel["per_year_row_counts"] == {"2021": 1, "2023": 1}
    assert consistency["n"] == 2
    assert consistency["max_deviation_f"] == 0.0


def test_geography_and_population_manifests_hash_actual_inputs(tmp_path) -> None:
    """Section 4.7: geographic source manifests bind raw inputs to county metadata."""

    for directory in ("data/raw/geography", "data/raw/census", "data/metadata", "web/vendor"):
        (tmp_path / directory).mkdir(parents=True)
    gazetteer = tmp_path / "data/raw/geography/2020_Gaz_counties_national.zip"
    population = tmp_path / "data/raw/census/co-est2021-alldata.csv"
    counties = tmp_path / "data/metadata/counties.csv"
    vendor = tmp_path / "web/vendor/counties-albers-10m.json"
    records = ((gazetteer, b"gaz"), (population, b"pop"), (counties, b"county"), (vendor, b"map"))
    for path, contents in records:
        path.write_bytes(contents)
    gazetteer.with_name(gazetteer.name + ".http.json").write_text(
        '{"url":"https://www2.census.gov/example","retrieved_at_utc":"now"}'
    )
    geography, population_manifest = write_geography_population_manifests(tmp_path)
    geo = json.loads(geography.read_text())
    pop = json.loads(population_manifest.read_text())
    assert geo["source"]["sha256"] == sha256(gazetteer)
    assert geo["vendor_geometry"]["sha256"] == sha256(vendor)
    assert pop["source"]["sha256"] == sha256(population)


def test_data_qc_command_uses_the_full_derived_report_builder(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 4.6: CLI QC delegates to the registry and complete report builders."""

    from weather_basis.cli import _run_data

    (tmp_path / "config").mkdir()
    (tmp_path / "config/defaults.yaml").write_text("station: {}\n", encoding="utf-8")
    calls: list[tuple[str, object]] = []

    def fake_backfill(root):
        calls.append(("registry", root))

    def fake_reports(root, cfg):
        calls.append(("reports", (root, cfg)))
        return [root / "results/qc/panel_tavg.json"]

    monkeypatch.setattr("weather_basis.ingest.ghcnd.backfill_station_registry", fake_backfill)
    monkeypatch.setattr("weather_basis.ingest.qc.build_qc_reports", fake_reports)
    assert _run_data(Namespace(data_command="qc"), tmp_path) == 0
    assert [name for name, _ in calls] == ["registry", "reports"]
