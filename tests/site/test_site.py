"""Plan §§9.4 and 13: payload encoding and provenance checks."""

from __future__ import annotations

import numpy as np
import pandas as pd

from weather_basis.site.payloads import (
    _stations_payload,
    build_payloads,
    delta_decode,
    delta_encode,
    thin_draws,
)
from weather_basis.validation.provenance import forbidden_literals


def test_delta_encoding_round_trip() -> None:
    values = np.array([-2.501, -1.002, 0.0, 3.771])
    assert np.allclose(delta_decode(delta_encode(values)), values)


def test_thinning_includes_distribution_edges() -> None:
    values = thin_draws(np.arange(10_000), 1_000)
    assert len(values) == 1_000 and values[0] == 0 and values[-1] == 9_999


def test_provenance_scan_ignores_rendered_output(tmp_path) -> None:
    (tmp_path / "web/templates").mkdir(parents=True)
    (tmp_path / "site").mkdir()
    (tmp_path / "web/templates/page.j2").write_text("clean")
    (tmp_path / "site/index.html").write_text("46%")
    assert forbidden_literals(tmp_path) == []


def test_phase_six_payload_includes_draws_quotes_and_rung(tmp_path) -> None:
    (tmp_path / "data/metadata").mkdir(parents=True)
    (tmp_path / "results/atlas").mkdir(parents=True)
    (tmp_path / "results/draws/R2j").mkdir(parents=True)
    (tmp_path / "results/quotes").mkdir(parents=True)
    pd.DataFrame([{"fips": "31109", "name": "Lancaster", "state": "NE"}]).to_csv(
        tmp_path / "data/metadata/counties.csv", index=False
    )
    pd.DataFrame([{"pair": "HDD-01", "fips": "31109", "he_pit": 0.5}]).to_parquet(
        tmp_path / "results/atlas/pairs.parquet"
    )
    pd.DataFrame().to_parquet(tmp_path / "results/atlas/stations.parquet")
    np.save(tmp_path / "results/draws/R2j/HDD-01_31109_site.npy", np.arange(2_000.0))
    quote = pd.DataFrame(
        [{"pair": "HDD-01", "fips": "31109", "K": 100, "mid": 2, "ask": 3, "bid": 1}]
    )
    quote.to_parquet(
        tmp_path / "results/quotes/quotes.parquet"
    )
    build_payloads(tmp_path, tmp_path / "site", {"site": {"as_of": "2026-07-01"}})
    import gzip
    import json
    with gzip.open(tmp_path / "site/data/county/31109.json.gz", "rt") as stream:
        payload = json.load(stream)
    pair = payload["pairs"]["HDD-01"]
    assert len(pair["q"]) == 101 and len(pair["d"]) == 1_000
    assert pair["quotes"][0]["ask"] == 3.0 and pair["as_of"] == "2026-07-01"
    assert pair["rung"].startswith("R2j")


def test_station_registry_ghcnd_id_is_shipped() -> None:
    rows = pd.DataFrame([{"ghcnd_id": "USW00094846", "name": "O'Hare", "lat": 42, "lon": -87}])
    assert _stations_payload(rows)[0]["ghcn_id"] == "USW00094846"
