# ruff: noqa: E501
"""Readable B18/B19 evidence and observed/stress Scenario Room projections.

The builders in this module only project frozen reports and the frozen daily
panel.  In particular, they do not fit a weather model, choose a source year
after examining a hedge result, or attach probabilities to stress paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from weather_basis.contracts.calendar import PAIRS
from weather_basis.contracts.degree_days import daily_cdd, daily_hdd
from weather_basis.provenance.ids import content_id, file_sha256
from weather_basis.publishing.projections import envelope
from weather_basis.schemas.public import ResultEnvelope
from weather_basis.schemas.scenarios import ScenarioMatrix, ScenarioSet

CORE_COUNTIES = ("31055", "31109", "31079", "31111", "31157", "06037", "36061")
# These windows were registered before inspecting any portfolio or hedge gain.
# Do not replace a failed window with a prettier year without a new record.
REGISTERED_SOURCE_WINDOWS = (
    ("historical-observed-2013", 2013, "2012-07-01", "2013-06-30"),
    ("historical-observed-2015", 2015, "2014-07-01", "2015-06-30"),
    ("historical-observed-2022", 2022, "2021-07-01", "2022-06-30"),
)


def _sha(path: Path) -> str:
    return f"sha256:{file_sha256(path)}"


def _sources(root: Path, *paths: Path) -> tuple[str, ...]:
    vintage = root / "config/vintages/v1-frozen.yaml"
    return tuple(_sha(path) for path in paths if path.is_file()) + (_sha(vintage),)


def _latest_report(root: Path, name: str) -> tuple[Path, dict[str, Any]]:
    candidates = sorted((root / "results/v2/experiments" / name).glob("*/report.json"))
    if not candidates:
        raise FileNotFoundError(f"No frozen {name} report")
    path = candidates[-1]
    return path, json.loads(path.read_text())


def _context(
    root: Path, release_id: str, data_vintage_id: str, valuation_asof: str, *paths: Path
) -> dict[str, Any]:
    return {
        "release_id": release_id,
        "analysis_id": content_id({"evidence_surfaces": [str(path.relative_to(root)) for path in paths]}),
        "source_artifact_ids": _sources(root, *paths),
        "data_vintage_id": data_vintage_id,
        "valuation_asof": valuation_asof,
        "evidence_reference": "; ".join(str(path.relative_to(root)) for path in paths),
    }


def evidence_envelopes(
    root: Path | str,
    *,
    release_id: str,
    data_vintage_id: str = "v1-frozen-2026-09-05",
    valuation_asof: str = "2026-07-01",
) -> dict[str, ResultEnvelope]:
    """Return actual readable Research records for the frozen B20 evidence.

    These records intentionally retain partial status where the report is a
    bounded study or retrospective evidence rather than final national proof.
    """
    root = Path(root)
    r02_path, r02 = _latest_report(root, "R02")
    r03_path, r03 = _latest_report(root, "R03")
    r05_path, r05 = _latest_report(root, "R05")
    r04_path = root / "results/v2/experiments/R04-v3-corrected/report.json"
    r04 = json.loads(r04_path.read_text())
    r04_selected_path = root / "results/v2/experiments/R04-v3-corrected/accepted-generator-selection.json"
    r04_selected = json.loads(r04_selected_path.read_text())
    r01_path = root / "results/v2/r01-candidate/r01_protocol.json"
    r01 = json.loads(r01_path.read_text())
    case_path = sorted((root / "results/v2/cases/nebraska").glob("*/case.json"))[-1]
    case = json.loads(case_path.read_text())
    vintage_path = root / "config/vintages/v1-frozen.yaml"
    vintage = yaml.safe_load(vintage_path.read_text())
    support = vintage["support"]

    report_paths = (r01_path, r02_path, r03_path, r04_path, r04_selected_path, r05_path, case_path)
    common = _context(root, release_id, data_vintage_id, valuation_asof, *report_paths)

    def record(key: str, payload: dict[str, Any], *, status: str = "partial", reason: str = "bounded_or_retrospective_evidence") -> ResultEnvelope:
        return envelope(result_type="research_evidence", payload=payload, status=status, reason_code=reason, units="degree_days", **common)

    origin_rows = r04["rows"]
    return {
        "glossary": record("glossary", {
            "terms": [
                {"term": "replication_HE", "definition": "One minus uncentered residual SSE divided by centered target SST on the exact paired common seasons; unavailable for a degenerate target."},
                {"term": "economic_loss_and_ES", "definition": "A declared USD loss/payoff ledger evaluated on aligned scenario IDs. It is not a replication HE percentage and cannot be added across components."},
                {"term": "current_decision", "definition": "An as-of station choice made using information available before its period."},
                {"term": "historical_policy", "definition": "The chronological prior-only rule scored only after the held-out outcome is observed."},
                {"term": "physical_indication", "definition": "Expectation from frozen physical weather paths; it is neither a loaded indication nor a market quote."},
                {"term": "aligned_scenarios", "definition": "Rows sharing an explicit ScenarioSet ID and scenario IDs. Independently sorted marginals are display views, not a portfolio matrix."},
            ],
            "canonical_index": "HDD/CDD base 65 F; daily temperature then transform then monthly sum.",
        }),
        "method": record("method", {
            "r01": {"question": r01["question"], "policy": "corrected prior-score selection against nearest on matched seasons", "status": "source protocol registered"},
            "r02": {"scope": r02["scope"], "unit_of_inference": "20 chronological origins per reported place/pair", "selection": "prior-only sparse basket"},
            "r03": {"scope": r03["scope"], "comparison": "same observed-index book and five-station total constraint; not predictive common-scenario evidence"},
            "r04": {"selected_generator": r04_selected["selected_generator"], "disposition": r04_selected["disposition"], "origins": [row["origin"] for row in origin_rows]},
            "r05": {"scope": r05["scope"], "disposition": r05.get("disposition")},
            "nebraska_case": {"scope": case["scope"], "locations": case["mapping"], "interpretation": case["interpretation"]},
        }),
        "source_support": record("source_support", {
            "vintage_id": vintage["vintage_id"],
            "vintage_sha256": vintage["data_vintage_sha256"],
            "sources": [{key: item[key] for key in ("support_id", "artifact_id", "variable", "location_type", "coverage_start", "coverage_end", "coherent_through", "historical_availability", "aggregation_order", "unsupported_reason")} for item in support],
            "market_status": vintage["market_data_status"],
            "settlement_status": vintage["official_settlement_status"],
        }),
        "holdout": record("holdout", {
            "access_ledger": [{"period": "2023-01 through 2025-12", "status": "consumed exploratory/development evidence", "interpretation": "retrospective; it is not an untouched final holdout"}, {"period": "future origins", "status": "not yet observed", "interpretation": "requires a preregistered evaluation before a prospective claim"}],
            "scoreability": "A missing held-out station outcome makes the frozen policy unscoreable; it does not replace the choice.",
        }),
        "limitations": record("limitations", {
            "items": [
                "County nClimGrid and GHCN proxy indexes are frozen public research inputs, not official contract settlement records.",
                "Historical availability is retrospective because issue-time availability and revisions are unknown.",
                "R02/R03 are five-county observed-index studies; R05 is a bounded national sensitivity screen.",
                "R04 has two registered origins, so its generator selection is inconclusive rather than complexity proof.",
                "Stress paths are non-probabilistic and cannot produce predictive expected shortfall.",
            ]
        }),
        "performance": record("performance", {
            "r04_producer": r04["producer"],
            "peak_rss_bytes": r04["peak_rss_bytes"],
            "origins": [{key: row.get(key) for key in ("origin", "columns", "runtime_seconds", "peak_rss_bytes", "scoreability")} for row in origin_rows],
            "meaning": "Measured representative-origin timings; they are not a national throughput forecast.",
        }),
        "validation": record("validation", {
            "topology": {
                "marginal": "R04 reports mean CRPS and energy score separately for common-year and R2j candidates.",
                "dependence": "R04 uses common date-consistent columns over seven counties and 18 stations; it does not treat paths as independent observed years.",
                "downstream": "R02 sparse baskets, R03 joint observed-index book, R05 sensitivity screen, and the Nebraska case remain separate evidence tiers.",
            },
            "r04_origins": [
                {
                    "origin": row.get("origin"),
                    "fit_cutoff": row.get("fit_cutoff"),
                    "scoreability": row.get("scoreability", row.get("status")),
                    "common_year_mean_crps": row.get("scores", {})
                    .get("common_year_trend", {})
                    .get("mean_crps"),
                    "r2j_mean_crps": row.get("scores", {}).get("r2j", {}).get("mean_crps"),
                    "unavailable_reason": row.get("reason"),
                }
                for row in origin_rows
            ],
            "uncertainty": "Origin/season clusters are the unit of observed evidence. Simulation paths do not increase the number of historical years.",
        }),
    }


def _scenario_set(*, scenario_type: str, scenario_ids: tuple[str, ...], weights: tuple[float, ...] | None, locations: tuple[str, ...], data_vintage_id: str, valuation_asof: str, construction: str) -> ScenarioSet:
    scenario_set_id = content_id({"type": scenario_type, "ids": scenario_ids, "locations": locations, "construction": construction, "vintage": data_vintage_id})
    return ScenarioSet(
        scenario_set_id=scenario_set_id, scenario_type=scenario_type, scenario_ids=scenario_ids,
        probability_weights=weights, calendar_id="gregorian-local-observation-date",
        date_start="2012-07-01", date_end="2022-06-30", location_ids=locations,
        generator_spec_id="frozen-observed-stress-projection-v1", common_random_plan_id=content_id({"construction": construction}),
        data_vintage_id=data_vintage_id, model_spec_ids=("observed-daily-temperature-v1",),
        valuation_asof=valuation_asof, scenario_id_hash=content_id(list(scenario_ids)),
    )


def _monthly(paths: np.ndarray, dates: pd.DatetimeIndex, scenario_set: ScenarioSet, locations: tuple[str, ...]) -> ScenarioMatrix:
    columns, entities = [], []
    for pair in PAIRS:
        masked = paths[:, dates.month == pair.month, :]
        values = daily_hdd(masked, base=65.0).sum(axis=1) if pair.index == "HDD" else daily_cdd(masked, base=65.0).sum(axis=1)
        columns.extend(values[:, index] for index in range(len(locations)))
        entities.extend(f"{location}:{pair.key}" for location in locations)
    return ScenarioMatrix(parent_scenario_set_id=scenario_set.scenario_set_id, scenario_ids=scenario_set.scenario_ids, entity_ids=tuple(entities), values=np.column_stack(columns), units="degree_days")


def scenario_room_envelopes(
    root: Path | str,
    *,
    release_id: str,
    data_vintage_id: str = "v1-frozen-2026-09-05",
    valuation_asof: str = "2026-07-01",
) -> dict[str, ResultEnvelope]:
    """Project bounded observed and stylized stress paths for Scenario Room.

    The output uses existing ``ScenarioSet`` and ``ScenarioMatrix`` contracts.
    Daily values are a compact aligned, three-dimensional companion to the
    monthly matrix: ``scenario, date, location`` in degF.
    """
    root = Path(root)
    panel = root / "data/panel"
    dates = pd.DatetimeIndex(np.load(panel / "dates.npy", mmap_mode="r", allow_pickle=False))
    fips = tuple(str(value) for value in np.load(panel / "fips.npy", mmap_mode="r", allow_pickle=False))
    county_lookup = {fips_value: index for index, fips_value in enumerate(fips)}
    station_ids = tuple(str(value) for value in np.load(panel / "station_ids.npy", mmap_mode="r", allow_pickle=False))
    counties = np.load(panel / "tavg_f32.npy", mmap_mode="r", allow_pickle=False)
    stations = np.load(panel / "stations_tbar_f32.npy", mmap_mode="r", allow_pickle=False)
    locations = CORE_COUNTIES + station_ids
    selected: list[tuple[str, int, str, str, np.ndarray, pd.DatetimeIndex]] = []
    unavailable: list[dict[str, Any]] = []
    for scenario_id, season, start, end in REGISTERED_SOURCE_WINDOWS:
        mask = (dates >= start) & (dates <= end)
        window_dates = dates[mask]
        values = np.column_stack((counties[mask][:, [county_lookup[x] for x in CORE_COUNTIES]], stations[mask]))
        if len(window_dates) != 365 or not np.array_equal(window_dates, pd.date_range(start, end, freq="D")):
            unavailable.append({"scenario_id": scenario_id, "source_year": season, "window_start": start, "window_end": end, "reason_code": "incomplete_daily_date_grid"})
        elif not np.isfinite(values).all():
            unavailable.append({"scenario_id": scenario_id, "source_year": season, "window_start": start, "window_end": end, "reason_code": "missing_daily_temperature_support", "missing_location_ids": [locations[index] for index in np.flatnonzero(~np.isfinite(values).all(axis=0))]})
        else:
            selected.append((scenario_id, season, start, end, np.asarray(values, dtype=float), window_dates))
    if not selected:
        raise ValueError("No registered Scenario Room source year has complete common support")
    historical_ids = tuple(item[0] for item in selected)
    historical = _scenario_set(scenario_type="historical", scenario_ids=historical_ids, weights=tuple([1 / len(selected)] * len(selected)), locations=locations, data_vintage_id=data_vintage_id, valuation_asof=valuation_asof, construction="registered_observed_windows")
    daily = np.stack([item[4] for item in selected])
    representative_dates = selected[0][5]
    historical_payload = {
        "scenario_set": historical.to_dict(),
        "source_windows": [{"scenario_id": item[0], "source_year": item[1], "window_start": item[2], "window_end": item[3], "type": "observed_empirical"} for item in selected],
        "unavailable_windows": unavailable,
        "daily_temperature": {"matrix_kind": "aligned_daily_temperature", "axes": ["scenario_id", "local_date", "location_id"], "dates": [value.date().isoformat() for value in representative_dates], "location_ids": list(locations), "values": daily.tolist(), "units": "degF"},
        "monthly_degree_days": _monthly(daily, representative_dates, historical, locations).to_dict(),
        "probability_interpretation": "Empirical equal weights for the displayed complete observed seasons only; not a fitted predictive distribution.",
        "cost_policy": "Frozen physical weather inputs only; no market cost or predictive ES is computed here.",
    }
    source_paths = (panel / "dates.npy", panel / "fips.npy", panel / "station_ids.npy", panel / "tavg_f32.npy", panel / "stations_tbar_f32.npy")
    common = _context(root, release_id, data_vintage_id, valuation_asof, *source_paths)
    output = {"historical": envelope(result_type="scenario_room", payload=historical_payload, scenario_set_id=historical.scenario_set_id, units="degree_days", **common)}
    base_id, source_year, start, end, base_values, base_dates = selected[0]
    stresses = (("uniform_warm_3f", "+3F uniform temperature shift", np.full(len(locations), 3.0)), ("uniform_cold_3f", "-3F uniform temperature shift", np.full(len(locations), -3.0)), ("nebraska_warm_3f", "+3F only for the five Nebraska county locations", np.array([3.0] * 5 + [0.0] * (len(locations) - 5))))
    for name, description, shift in stresses:
        stress_id = f"stress-{name}-{source_year}"
        stress = _scenario_set(scenario_type="stress", scenario_ids=(stress_id,), weights=None, locations=locations, data_vintage_id=data_vintage_id, valuation_asof=valuation_asof, construction=f"{name}:{base_id}")
        stress_daily = (base_values + shift[None, :])[None, :, :]
        output[f"stress:{name}"] = envelope(result_type="scenario_room", scenario_set_id=stress.scenario_set_id, units="degree_days", payload={
            "scenario_set": stress.to_dict(), "source_windows": [{"scenario_id": stress_id, "source_year": source_year, "window_start": start, "window_end": end, "source_historical_scenario_id": base_id}],
            "daily_temperature": {"matrix_kind": "aligned_daily_temperature", "axes": ["scenario_id", "local_date", "location_id"], "dates": [value.date().isoformat() for value in base_dates], "location_ids": list(locations), "values": stress_daily.tolist(), "units": "degF"},
            "monthly_degree_days": _monthly(stress_daily, base_dates, stress, locations).to_dict(),
            "construction": description, "probability_interpretation": "No probability weights or return period. This is a stylized sensitivity, not a predictive scenario.",
            "cost_policy": "Frozen physical weather inputs only; predictive ES and weather fitting are intentionally unavailable.", "unavailable_windows": unavailable,
        }, **common)
    return output
