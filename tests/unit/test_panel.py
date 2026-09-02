"""Unit coverage for plan section 4.3 daily panel assembly and loading."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather_basis.ingest import panel
from weather_basis.ingest.nclimgrid import Month


class County:
    def __init__(self, fips: str) -> None:
        self.fips = fips


def test_build_panel_orders_counties_and_persists_date_axis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 4.3: panels are date-major float32 arrays in ascending FIPS order."""

    raw = tmp_path / "raw" / "averages" / "2001"
    raw.mkdir(parents=True)
    (raw / "tavg-200101-cty-scaled.csv").touch()
    (raw / "tavg-200102-cty-scaled.csv").touch()

    def fake_parse(path: Path, *_args: object) -> tuple[np.ndarray, list[County]]:
        if "200101" in path.name:
            first = np.tile(np.array([[3, 1]], dtype=np.float32), (31, 1))
            return first, [County("31001"), County("01001")]
        second = np.tile(np.array([[7, 5]], dtype=np.float32), (28, 1))
        return second, [County("31001"), County("01001")]

    monkeypatch.setattr(panel, "parse_month", fake_parse)
    counties = pd.DataFrame({"fips": ["01001", "31001"], "ncei_code": ["01001", "31001"]})
    report = panel.build_panel(
        "tavg", [Month(2001, 1), Month(2001, 2)], tmp_path / "raw", tmp_path / "out", counties
    )
    values = np.load(tmp_path / "out" / "tavg_f32.npy")
    assert report.n_days == 59
    assert values.dtype == np.float32
    assert np.allclose(
        values[[0, 30, 31]],
        [[33.8, 37.4], [33.8, 37.4], [41.0, 44.6]],
        rtol=0,
        atol=2e-6,
    )
    assert np.load(tmp_path / "out" / "dates.npy").astype("datetime64[D]").tolist()[
        -1
    ] == np.datetime64("2001-02-28").astype(object)


def test_build_panel_rejects_monthly_county_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 4.3: a panel cannot silently drop or add county columns."""

    raw = tmp_path / "raw" / "averages" / "2001"
    raw.mkdir(parents=True)
    (raw / "tavg-200101-cty-scaled.csv").touch()
    monkeypatch.setattr(
        panel,
        "parse_month",
        lambda *_args: (np.ones((31, 1), dtype=np.float32), [County("01001")]),
    )
    with pytest.raises(panel.PanelError, match="county dimension"):
        panel.build_panel(
            "tavg",
            [Month(2001, 1)],
            tmp_path / "raw",
            tmp_path / "out",
            pd.DataFrame({"fips": ["01001", "31001"]}),
        )
