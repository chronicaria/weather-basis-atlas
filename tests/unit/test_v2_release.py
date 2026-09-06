"""B23 fixture release sealing, tamper detection, and local recovery."""

import json
from pathlib import Path

import pytest

from weather_basis.provenance.ids import file_sha256
from weather_basis.publishing.release import (
    _tree_sha256,
    build_release,
    inspect_release,
    rollback_release,
    verify_release,
)


def _fixture_lock(root: Path) -> Path:
    source = root / "public-source.json"
    source.write_text('{"candidate":"fixture"}\n', encoding="utf-8")
    template = root / "templates" / "page.html"
    template.parent.mkdir()
    template.write_text("fixture template\n", encoding="utf-8")
    artifact = root / "accepted" / "fixture.json"
    artifact.parent.mkdir()
    artifact.write_text('{"result":"accepted"}\n', encoding="utf-8")
    legacy = root / "v1-source" / "index.html"
    legacy.parent.mkdir()
    legacy.write_text(
        "<html><script>const archiveToken = '}}';</script><body>V1 archive</body></html>\n",
        encoding="utf-8",
    )
    lock = {
        "schema_version": "2.0",
        "research": {
            "scientific_config_id": "config:fixture",
            "vintage_lock_id": "vintage:fixture",
            "model_spec_ids": ["model:fixture"],
            "scenario_set_ids": ["scenario:fixture"],
            "experiment_ids": ["experiment:fixture"],
            "numerical_environment": "python-fixture",
        },
        "presentation": {
            "base_path": "/weather-basis-atlas/",
            "source_hashes": {"templates/page.html": file_sha256(template)},
        },
        "artifacts": [
            {
                "artifact_id": "artifact:fixture",
                "path": "accepted/fixture.json",
                "sha256": file_sha256(artifact),
                "access_class": "public_release",
            }
        ],
        "public_source": {"path": "public-source.json", "sha256": file_sha256(source)},
        "legacy_bundle": {"path": "v1-source", "sha256": _tree_sha256(legacy.parent)},
        "route_map": {
            "/": "index.html",
            "/compare": "compare.html",
            "/contract": "contract.html",
            "/portfolio": "portfolio.html",
            "/research/": "research/index.html",
        },
    }
    path = root / "fixture-lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


def _builder(
    *, root: Path, out: Path, release_id: str, lock: dict[str, object]
) -> dict[str, object]:
    del root, lock
    routes = (
        "index.html",
        "compare.html",
        "contract.html",
        "portfolio.html",
        "research/index.html",
    )
    for route in routes:
        path = out / route
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"<html><body>{route}</body></html>\n", encoding="utf-8")
    (out / "data").mkdir()
    (out / "data" / "bootstrap.json").write_text(
        json.dumps({"schema_version": "2.0", "release_id": release_id}), encoding="utf-8"
    )
    (out / "v1").mkdir()
    (out / "v1" / "index.html").write_text(
        "<html><script>const archiveToken = '}}';</script><body>V1 archive</body></html>\n",
        encoding="utf-8",
    )
    return {"pages": len(routes)}


def test_build_seals_fresh_fixture_release_and_inspects_it(tmp_path: Path) -> None:
    lock = _fixture_lock(tmp_path)
    bundle = tmp_path / "releases" / "fixture"

    report = build_release(tmp_path, lock, bundle, builder=_builder)

    assert report["bundle"] == str(bundle.resolve())
    assert report["file_count"] == 8  # five pages, data, V1, copied lock; manifest excluded
    assert set(report["routes"]) == {"/", "/compare", "/contract", "/portfolio", "/research/"}
    assert inspect_release(bundle)["release_id"] == report["release_id"]
    assert (bundle / "release-lock.json").is_file()
    assert (bundle / "v1" / "index.html").is_file()
    assert "}}" in (bundle / "v1" / "index.html").read_text(encoding="utf-8")


def test_tampering_and_unknown_bundle_schema_fail(tmp_path: Path) -> None:
    lock = _fixture_lock(tmp_path)
    bundle = tmp_path / "bundle"
    build_release(tmp_path, lock, bundle, builder=_builder)
    (bundle / "compare.html").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="bundle file"):
        verify_release(bundle)

    build_release(tmp_path, lock, tmp_path / "fresh", builder=_builder)
    extra = tmp_path / "fresh" / "stale.json"
    extra.write_text("{}")
    with pytest.raises(ValueError, match="unlisted"):
        verify_release(tmp_path / "fresh")
    extra.unlink()
    manifest = json.loads((tmp_path / "fresh" / "bundle-manifest.json").read_text())
    manifest["schema_version"] = "999"
    (tmp_path / "fresh" / "bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown bundle schema"):
        verify_release(tmp_path / "fresh")


def test_rollback_recovers_verified_prior_bundle_to_explicit_target(tmp_path: Path) -> None:
    lock = _fixture_lock(tmp_path)
    bundle = tmp_path / "bundle"
    build_release(tmp_path, lock, bundle, builder=_builder)

    report = rollback_release(bundle, tmp_path / "recovered" / "fixture")

    assert report["release_id"] == inspect_release(bundle)["release_id"]
    assert (tmp_path / "recovered" / "fixture" / "portfolio.html").is_file()
