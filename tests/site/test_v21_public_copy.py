"""V2.1 presentation checks: formatting helpers and identifier-free templates."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = [
    ROOT / "apps/site/templates/index.html",
    ROOT / "apps/site/templates/compare.html",
    ROOT / "apps/site/templates/contract.html",
    ROOT / "apps/site/templates/portfolio.html",
    ROOT / "apps/site/templates/research/index.html",
]


def test_format_helpers_render_plain_language() -> None:
    script = r"""
import assert from 'node:assert/strict';
import * as f from './apps/site/js/pages/format.js';
assert.equal(f.pct(0.6788), '67.9%');
assert.equal(f.pct(null), 'Unavailable');
assert.equal(f.pts(0.0286), '+2.9 pts');
assert.equal(f.pts(-0.0433), '−4.3 pts');
assert.equal(f.usd(1137.25), '$1,137');
assert.equal(f.usd(-245.6, 2), '−$245.60');
assert.equal(f.num(0), '0');
assert.equal(f.km(536.06), '536 km');
assert.equal(f.dateShort('2026-07-01'), '1 Jul 2026');
assert.equal(f.seasonRange([1981, 1982, 1983]), '1981–1983');
assert.equal(f.pairLabel('HDD-01'), 'January heating degree days');
assert.equal(f.pairLabel('CDD-07', {short: true}), 'Jul CDD');
assert.equal(f.stationCity('USW00003927:HDD-01'), 'Dallas-Fort Worth');
assert.equal(f.stationId('Dallas-Fort Worth International'), 'USW00003927');
const release = 'release:306bdf8f6a3a1c31762f00b668d43e26f1cf0a33273dc51baf23f9d7635bef74';
assert.equal(f.shortId(release), '306bdf8f');
const availability = {status: 'eligible_modeled_proxy', reason_code: 'selected'};
assert.match(f.statusText(availability), /station is available to hedge/);
assert.equal(f.humanize('unavailable_aligned_station_model'), 'Unavailable aligned station model');
// Negative numbers use a true minus everywhere, and ranges read "to".
assert.equal(f.pct(-0.023), '\u22122.3%');
assert.equal(f.num(-51652), '\u221251,652');
assert.equal(f.ratio(-0.0001), '0.00');
assert.equal(f.ratio(-0.13), '\u22120.13');
assert.equal(f.rangeText(-2502, 2679, f.usd), '\u2212$2,502 to $2,679');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_templates_keep_identifiers_out_of_visible_copy() -> None:
    for template in TEMPLATES:
        text = template.read_text()
        assert text.lower().count("<h1") == 1, template
        visible = re.sub(r"<code>.*?</code>", "", text, flags=re.S)
        visible = re.sub(r"<[^>]+>", " ", visible)
        assert not re.search(r"[a-f0-9]{24,}", visible), template
        assert "__WBA_RELEASE_ID__" in text, "footer must carry the release placeholder"
        for jargon in ("DTO", "committed", "envelope"):
            assert jargon not in visible, (template, jargon)
