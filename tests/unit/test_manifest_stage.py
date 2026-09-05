"""Tests for complete, filesystem-derived stage provenance manifests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from weather_basis.config import load_config
from weather_basis.io import sha256 as file_sha256
from weather_basis.manifest import Manifest, _dirty_before_start, read_manifest
from weather_basis.manifest_stage import (
    output_hashes,
    write_data_qc_manifest,
    write_models_fit_manifest,
    write_release_manifest,
    write_reproduction_manifest,
    write_sensitivity_manifest,
    write_stage_manifest,
)


def _project(root: Path) -> tuple[Path, object]:
    (root / "docs").mkdir(parents=True)
    prereg = root / "docs" / "preregistration.md"
    prereg.write_text("locked protocol\n", encoding="utf-8")
    digest = sha256(prereg.read_bytes()).hexdigest()
    config = root / "defaults.yaml"
    config.write_text(
        "\n".join(
            (
                "seed: 17",
                "allow_dirty: true",
                "vintages: {county: county-v1, geography: geo-v1}",
                f"prereg: {{sha256: {digest}}}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return root, load_config(config)


def test_stage_manifest_hashes_real_outputs_and_complete_provenance(tmp_path: Path) -> None:
    root, cfg = _project(tmp_path / "repo")
    output = root / "results" / "atlas" / "result.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"first result")

    target = write_stage_manifest(
        root,
        cfg,
        stage="atlas",
        outputs=[root / "results" / "atlas"],
        paths_in=[root / "docs" / "preregistration.md"],
        started_at=datetime.now(UTC),
    )
    manifest = read_manifest(target)
    assert manifest.config_hash
    assert manifest.git_commit
    assert manifest.vintages == {"county": "county-v1", "geography": "geo-v1"}
    assert manifest.geography_vintage == "geo-v1"
    assert manifest.seed == 17
    assert manifest.holdout_unlocked is False
    prereg_hash = sha256((root / "docs/preregistration.md").read_bytes()).hexdigest()
    assert manifest.prereg_sha256 == prereg_hash
    assert manifest.sha256_out == {"results/atlas/result.bin": file_sha256(output)}
    assert manifest.extra["sha256_in"] == {
        "docs/preregistration.md": file_sha256(root / "docs/preregistration.md")
    }
    assert manifest.paths_out == ["results/atlas/result.bin", "results/manifests/atlas.json"]
    assert manifest.extra["self_excluded_from_sha256"] == "results/manifests/atlas.json"


def test_output_hashes_reject_missing_outputs(tmp_path: Path) -> None:
    root, _ = _project(tmp_path / "repo")
    try:
        output_hashes(root, [root / "results" / "absent.parquet"])
    except FileNotFoundError as exc:
        assert "absent.parquet" in str(exc)
    else:  # pragma: no cover - makes the intended failure mode explicit
        raise AssertionError("missing output was accepted")


def test_reproduction_manifest_records_actual_hash_equality(tmp_path: Path) -> None:
    reference, cfg = _project(tmp_path / "reference")
    reproduced, _ = _project(tmp_path / "reproduced")
    files = {
        "results/atlas/headline.json": b'{"headline": true}\n',
        "results/atlas/pairs.parquet": b"pairs bytes",
        "results/quotes/quotes.parquet": b"quotes bytes",
    }
    for root in (reference, reproduced):
        for relative, contents in files.items():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
    snapshot = tmp_path / "wba-raw.tar"
    snapshot.write_bytes(b"snapshot")

    target = write_reproduction_manifest(
        reference,
        cfg,
        reference_root=reference,
        reproduced_root=reproduced,
        snapshot=snapshot,
        parquet_filenames=["results/atlas/pairs.parquet", "results/quotes/quotes.parquet"],
        source_commit="a" * 40,
        started_at=datetime.now(UTC),
    )
    manifest = read_manifest(target)
    assert manifest.stage == "reproduce"
    assert manifest.extra["hash_equality"] == {
        "headline.json": True,
        "pairs.parquet": True,
        "quotes.parquet": True,
    }
    assert manifest.extra["fresh_clone"] is True
    assert manifest.extra["source_commit"] == "a" * 40
    assert all(manifest.extra["parquet_hash_equality"].values())
    assert manifest.extra["reference_hashes"]["quotes.parquet"] == file_sha256(
        reference / "results/quotes/quotes.parquet"
    )
    assert str(snapshot.resolve()) in manifest.extra["sha256_in"]
    assert "results/atlas/pairs.parquet" in manifest.extra["sha256_in"]


def test_named_stage_helpers_preserve_inputs_and_do_not_forge_release_url(tmp_path: Path) -> None:
    root, cfg = _project(tmp_path / "repo")
    panel = root / "data/panel/tavg_f32.npy"
    panel.parent.mkdir(parents=True)
    panel.write_bytes(b"panel")
    qc = root / "results/qc/panel.json"
    qc.parent.mkdir(parents=True)
    qc.write_bytes(b"qc")
    blocks = root / "data/panel/mean_blocks.npz"
    blocks.write_bytes(b"blocks")
    sensitivity_input = root / "results/tournament/selection.parquet"
    sensitivity_input.parent.mkdir(parents=True)
    sensitivity_input.write_bytes(b"selection")
    sensitivity = root / "results/sensitivities/table.parquet"
    sensitivity.parent.mkdir(parents=True)
    sensitivity.write_bytes(b"sensitivity")
    site = root / "site/index.html"
    site.parent.mkdir(parents=True)
    site.write_text("site", encoding="utf-8")
    readme = root / "README.md"
    readme.write_text("release", encoding="utf-8")

    qc_manifest = read_manifest(
        write_data_qc_manifest(
            root, cfg, outputs=[qc], inputs=[panel], started_at=datetime.now(UTC)
        )
    )
    fit_manifest = read_manifest(
        write_models_fit_manifest(
            root, cfg, outputs=[blocks], inputs=[panel], started_at=datetime.now(UTC)
        )
    )
    sensitivity_manifest = read_manifest(
        write_sensitivity_manifest(
            root,
            cfg,
            outputs=[sensitivity],
            inputs=[sensitivity_input, blocks],
            started_at=datetime.now(UTC),
        )
    )
    release_manifest = read_manifest(
        write_release_manifest(
            root,
            cfg,
            live_url="https://unit.test",
            live_smoke={"passed": True, "external_requests": 0},
            outputs=[site, readme],
            inputs=[sensitivity, qc],
            started_at=datetime.now(UTC),
        )
    )
    assert qc_manifest.stage == "data_qc"
    assert fit_manifest.stage == "models_fit"
    assert sensitivity_manifest.extra["sha256_in"]["data/panel/mean_blocks.npz"] == file_sha256(
        blocks
    )
    assert release_manifest.extra["live_url"] == "https://unit.test"
    assert release_manifest.extra["live_smoke"] == {
        "passed": True,
        "external_requests": 0,
    }
    try:
        write_release_manifest(
            root,
            cfg,
            live_url="https://example.com",
            outputs=[site],
            inputs=[sensitivity],
            started_at=datetime.now(UTC),
        )
    except ValueError as exc:
        assert "real HTTPS" in str(exc)
    else:  # pragma: no cover - makes a placeholder release a hard failure
        raise AssertionError("placeholder release URL was accepted")


def test_dirty_rule_treats_a_tracked_deletion_as_preexisting_change(
    tmp_path: Path, monkeypatch
) -> None:
    root, _ = _project(tmp_path / "repo")
    deleted = root / "src" / "removed.py"
    deleted.parent.mkdir()
    deleted.write_text("gone\n", encoding="utf-8")
    deleted.unlink()
    manifest = Manifest(
        run_id="run",
        stage="atlas",
        created_utc="2026-09-02T00:00:00+00:00",
        git_commit="commit",
        config_hash="config",
        vintages={},
        geography_vintage="geo",
        seed=1,
        paths_in=[],
        paths_out=[],
        sha256_out={},
        holdout_unlocked=False,
        prereg_sha256=None,
        extra={},
    )
    monkeypatch.setattr("weather_basis.manifest._repo_root", lambda: root)
    monkeypatch.setattr("weather_basis.manifest._changed_tracked_files", lambda _: {deleted})
    assert _dirty_before_start(manifest, datetime.now(UTC)) == ["src/removed.py"]


def test_rerun_owns_the_prior_manifest_for_clean_tree_check(tmp_path: Path, monkeypatch) -> None:
    root, cfg = _project(tmp_path / "repo")
    cfg = load_config(root / "defaults.yaml", {"allow_dirty": False})
    output = root / "results/atlas/pairs.parquet"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"pairs")
    prior = root / "results/manifests/atlas.json"
    prior.parent.mkdir(parents=True)
    prior.write_text("old manifest\n", encoding="utf-8")
    before = datetime.now(UTC)
    os.utime(prior, (before.timestamp() - 2, before.timestamp() - 2))
    monkeypatch.setattr("weather_basis.manifest._changed_tracked_files", lambda _: {prior})

    target = write_stage_manifest(
        root, cfg, stage="atlas", outputs=[output], started_at=before
    )
    assert target == prior
