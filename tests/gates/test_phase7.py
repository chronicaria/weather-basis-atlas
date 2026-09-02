"""Plan Section 10, Phase 7: release and reproducibility gate."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_phase6() -> None:
    required = ("results/quotes/quotes.parquet", "results/quotes/coherence.json", "site/index.html")
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        pytest.skip(f"Phase 7 requires completed Phase 6 artifacts: {', '.join(missing)}")


def test_phase7_rendered_release_has_no_placeholder_slots() -> None:
    """Plan Sections 1, 10 Phase 7, and 13.9: release output has no unresolved placeholder."""
    targets = [ROOT / "README.md", *[path for path in (ROOT / "site").rglob("*") if path.is_file()]]
    for path in targets:
        if path.suffix in {".gz", ".png", ".jpg", ".pdf", ".mp4"}:
            continue
        assert "not yet computed" not in path.read_text(encoding="utf-8", errors="ignore")


def test_phase7_reproduction_manifest_records_hash_equality() -> None:
    """Plan Section 10 Phase 7: fresh-clone reproduction records release-hash equality."""
    manifest_path = ROOT / "results/manifests/reproduce.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    compared = manifest.get("hash_equality", manifest.get("extra", {}).get("hash_equality", {}))
    for filename in ("headline.json", "pairs.parquet", "quotes.parquet"):
        assert compared.get(filename) is True
    parquet = manifest.get(
        "parquet_hash_equality", manifest.get("extra", {}).get("parquet_hash_equality", {})
    )
    assert parquet and all(parquet.values())
    assert (
        manifest.get("fresh_clone") is True
        or manifest.get("extra", {}).get("fresh_clone") is True
    )


def test_phase7_live_release_serves_required_payloads() -> None:
    """Plan Section 10 Phase 7: deployed home, metadata, and default county all return HTTP 200."""
    release = json.loads((ROOT / "results/manifests/release.json").read_text(encoding="utf-8"))
    base_url = release["live_url"].rstrip("/")
    for suffix in ("index.html", "data/meta.json", "data/county/31109.json.gz"):
        with urlopen(f"{base_url}/{suffix}", timeout=30) as response:  # noqa: S310
            assert response.status == 200
    smoke = release.get("live_smoke", {})
    assert smoke.get("passed") is True
    assert smoke.get("external_requests") == 0
