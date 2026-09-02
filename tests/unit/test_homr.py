"""Build-plan Section 4.5: HOMR station-history event extraction."""

from __future__ import annotations

import json

from weather_basis.ingest.homr import parse_station


def test_homr_extracts_only_dated_relevant_change_fields(tmp_path) -> None:
    """Section 4.5: dated location, instrument and observation-time events are retained."""
    source = tmp_path / "USW00094846.json"
    source.write_text(
        json.dumps(
            {
                "station": {"ghcndId": "USW00094846", "name": "Chicago"},
                "history": [
                    {"effectiveDate": "1980-02-03", "latitude": {"old": 41.1, "new": 41.2}},
                    {"date": "1981-04-05", "observationTime": "2359"},
                    {"date": "1982-05-06", "instrument": "ASOS"},
                    {"date": "1983-01-01", "name": "not an event"},
                ],
            }
        ),
        encoding="utf-8",
    )
    events = parse_station(source)
    assert events.event_type.tolist() == ["location", "observation_time", "equipment"]
    assert events.ghcnd_id.tolist() == ["USW00094846"] * 3
    assert events.new_value.tolist() == ["41.2", "2359", "ASOS"]
