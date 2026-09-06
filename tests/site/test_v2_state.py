"""Focused B07 state regressions; these run without a browser or numerical data."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_v2_scenario_codec_and_explicit_county_commit() -> None:
    script = r'''
import assert from 'node:assert/strict';
import {decodeScenario, encodeScenario} from './apps/site/js/state/scenario.js';
import {findCountyMatches, createSelectionController} from './apps/site/js/state/selection.js';
globalThis.window = {location: {search: '', hash: ''}};
const encoded = encodeScenario({
  releaseId:'release-1', fips:'17031', indexId:'CDD-07', strike:123.5,
});
window.location.search = encoded;
assert.equal(decodeScenario().scenario.fips, '17031');
assert.equal(decodeScenario().scenario.strike, 123.5);
const research = decodeScenario('?record=research:next_station').scenario;
assert.equal(research.researchRecord, 'research:next_station');
const pinnedResearch = encodeScenario({...research, releaseId:'release-1'});
assert.equal(decodeScenario(pinnedResearch).scenario.researchRecord, 'research:next_station');
assert.equal(
  decodeScenario('?record=research:missing').scenario.researchRecord, 'research:missing');
const counties = [{name:'Cook',state:'GA',fips:'13051'}, {name:'Cook',state:'IL',fips:'17031'}];
assert.equal(findCountyMatches(counties, 'Cook').length, 2);
let resolveOld, resolveNew, visible = [];
const loadCounty = (fips, signal) => new Promise((resolve, reject) => {
  signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  if (fips === '13051') resolveOld = resolve; else resolveNew = resolve;
});
const controller = createSelectionController({
  initialFips:'31109', loadCounty, onChange:(event) => visible.push(event),
});
const old = controller.commit('13051');
const fresh = controller.commit('17031');
resolveNew({meta:{fips:'17031'}});
assert.equal((await fresh).ok, true);
assert.equal((await old).stale, true);
assert.equal(controller.committedFips, '17031');
assert.equal(visible.at(-1).visibleFips, '17031');
'''
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_v2_fixture_has_strict_bootstrap_identity_and_no_metrics() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/v2/public_bootstrap.json").read_text())
    assert fixture["schema_version"] == "2.0"
    registry = fixture["objects"]["county-registry-fixture"]
    assert registry["release_id"] == fixture["release_id"]
    assert registry["status"] == "available" and registry["reason_code"] is None
    counties = registry["payload"]["counties"]
    assert all(set(county) == {"fips", "name", "state"} for county in counties)


def test_v2_source_has_one_h1_per_route_and_no_v1_mutation() -> None:
    routes = [
        ROOT / "apps/site/templates/index.html",
        ROOT / "apps/site/templates/compare.html",
        ROOT / "apps/site/templates/contract.html",
        ROOT / "apps/site/templates/portfolio.html",
        ROOT / "apps/site/templates/research/index.html",
    ]
    assert all(route.read_text().lower().count("<h1") == 1 for route in routes)
    assert not (ROOT / "apps/site/templates/index.html").read_text().count("he_pit")
