"""Unit coverage for plan Section 4.2 migration and snapshot re-verification."""

from __future__ import annotations

import csv
from pathlib import Path

from weather_basis.ingest.migrate import export_snapshot, import_snapshot, migrate_legacy
from weather_basis.io import sha256


def _make_donor(root: Path) -> None:
    raw = root / "data/raw/nclimgrid_daily"
    average = raw / "averages/1951/tavg-195101-cty-scaled.csv"
    version = raw / "version/1951/ncdd-195101-version.txt"
    average.parent.mkdir(parents=True)
    version.parent.mkdir(parents=True)
    average.write_text("raw county data\n", encoding="utf-8")
    version.write_text("nClimGrid downloaded on Sun Apr 30 11:32:03 2017\n", encoding="utf-8")
    metadata = root / "data/metadata"
    metadata.mkdir(parents=True)
    (metadata / "us-state-codes_ncei-to-fips.csv").write_text(
        "NCEI_code,FIPS_code\n04,06\n", encoding="utf-8"
    )
    fields = [
        "variable", "year_month", "status", "local_path", "sha256", "version_local_path",
        "version_sha256",
    ]
    manifest = metadata / "nclimgrid_download_manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "variable": "tavg", "year_month": "1951-01", "status": "scaled",
                "local_path": "raw/nclimgrid_daily/averages/1951/tavg-195101-cty-scaled.csv",
                "sha256": sha256(average),
                "version_local_path": "raw/nclimgrid_daily/version/1951/ncdd-195101-version.txt",
                "version_sha256": sha256(version),
            }
        )


def test_migrate_copies_snapshot_and_reverifies_hashes(tmp_path: Path) -> None:
    """Section 4.2: migration copies donor sources and records verified vintage metadata."""
    donor, repo = tmp_path / "donor", tmp_path / "repo"
    _make_donor(donor)
    (repo / "config").mkdir(parents=True)
    (repo / "config/data_vintage.yaml").write_text(
        "nclimgrid_tavg: {id: nclimgrid-daily_v1-0-0_snap-test}\n", encoding="utf-8"
    )

    report = migrate_legacy(donor, repo)

    assert report.ok
    assert report.files_copied == 3
    assert report.files_verified == 2
    manifest = report.manifest_path.read_text(encoding="utf-8")
    assert "nclimgrid-daily_v1-0-0_snap-test" in manifest
    assert "Sun Apr 30 11:32:03 2017" in manifest


def test_snapshot_import_rehashes_contents(tmp_path: Path) -> None:
    """Section 4.2: importing a portable snapshot never fetches and repeats hash validation."""
    donor, source_repo, restored = tmp_path / "donor", tmp_path / "source", tmp_path / "restored"
    _make_donor(donor)
    migrate_legacy(donor, source_repo)
    archive = export_snapshot(source_repo, tmp_path / "vintage.tar.gz")

    report = import_snapshot(archive, restored)

    assert report.ok
    assert report.files_verified == 2
    assert (restored / "data/raw/SHA256SUMS").is_file()
    restored_raw = restored / "data/raw/nclimgrid_daily/averages/1951/tavg-195101-cty-scaled.csv"
    assert restored_raw.is_file()
