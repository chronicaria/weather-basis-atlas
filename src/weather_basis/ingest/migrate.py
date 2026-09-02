"""Migration and snapshot transport for the frozen donor nClimGrid vintage."""
from __future__ import annotations

import csv
import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from weather_basis.ingest.nclimgrid import NClimGridError, verify_manifest
from weather_basis.io import atomic_write_bytes, sha256


@dataclass(frozen=True)
class MigrateReport:
    files_copied: int
    files_verified: int
    drift: tuple[str, ...]
    manifest_path: Path

    @property
    def ok(self) -> bool:
        return not self.drift


def migrate_legacy(donor_root: Path, repo_root: Path, *, verify: bool = True) -> MigrateReport:
    """Copy, never move, the donor raw source and attest its hashes before use."""
    donor_root, repo_root = donor_root.resolve(), repo_root.resolve()
    donor_manifest = donor_root / "data/metadata/nclimgrid_download_manifest.csv"
    crosswalk = donor_root / "data/metadata/us-state-codes_ncei-to-fips.csv"
    if not donor_manifest.is_file() or not crosswalk.is_file():
        raise FileNotFoundError("Donor does not contain the required nClimGrid metadata")
    rows = [row for row in _read_rows(donor_manifest) if row.get("variable") == "tavg"]
    if not rows or any(row.get("status") != "scaled" for row in rows):
        raise NClimGridError("V1 donor manifest must contain scaled TAVG rows")
    drift = _check_rows(rows, donor_root)
    destination_manifest = repo_root / "data/manifests/nclimgrid_tavg.csv"
    if verify and drift:
        return MigrateReport(0, len(rows) * 2, tuple(drift), destination_manifest)
    copied = 0
    for row in rows:
        for key in ("local_path", "version_local_path"):
            source, target = donor_root / "data" / row[key], repo_root / "data" / row[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or sha256(target) != sha256(source):
                shutil.copy2(source, target)
                copied += 1
    target_crosswalk = repo_root / "data/metadata/us-state-codes_ncei-to-fips.csv"
    target_crosswalk.parent.mkdir(parents=True, exist_ok=True)
    if not target_crosswalk.exists() or sha256(target_crosswalk) != sha256(crosswalk):
        shutil.copy2(crosswalk, target_crosswalk)
        copied += 1
    migrated_at = datetime.now(UTC).isoformat(timespec="seconds")
    for row in rows:
        version = donor_root / "data" / row["version_local_path"]
        row.update(
            {
                "vintage_id": _vintage_id(repo_root),
                "migrated_from": str(donor_root),
                "migrated_at_utc": migrated_at,
                "version_created_on": _version_created_on(version),
                "verified": True,
            }
        )
    _write_rows(rows, destination_manifest)
    report = verify_manifest(destination_manifest, repo_root / "data/raw/nclimgrid_daily")
    return MigrateReport(copied, report.files_checked, report.drift, destination_manifest)


def export_snapshot(repo_root: Path, dest_tar: Path) -> Path:
    """Archive every frozen input needed by an offline reproduction.

    Metadata is intentionally archived as a directory, rather than as the
    one crosswalk used by the first implementation.  County dimensions,
    station registries, and downloaded GHCN metadata are themselves frozen
    inputs to the atlas and a snapshot missing them is not reproducible.
    """
    repo_root = repo_root.resolve()
    write_sha256sums(repo_root)
    members = [
        repo_root / "data/raw",
        repo_root / "data/manifests",
        repo_root / "data/metadata",
    ]
    dest_tar.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest_tar, "w:gz") as archive:
        for member in members:
            if member.exists():
                archive.add(
                    member, arcname=member.relative_to(repo_root).as_posix(), recursive=True
                )
    return dest_tar


def import_snapshot(src_tar: Path, repo_root: Path) -> MigrateReport:
    """Import a snapshot safely, then re-hash rather than trusting its archive metadata."""
    repo_root = repo_root.resolve()
    with tarfile.open(src_tar, "r:*") as archive:
        _validate_members(archive, repo_root)
        archive.extractall(repo_root, filter="data")
    manifest = repo_root / "data/manifests/nclimgrid_tavg.csv"
    if not manifest.is_file():
        raise NClimGridError("Snapshot lacks data/manifests/nclimgrid_tavg.csv")
    checksum_drift = verify_sha256sums(repo_root)
    report = verify_manifest(manifest, repo_root / "data/raw/nclimgrid_daily")
    drift = tuple(sorted(set(report.drift).union(checksum_drift)))
    return MigrateReport(0, report.files_checked, drift, manifest)


def write_sha256sums(repo_root: Path) -> Path:
    raw = repo_root / "data/raw"
    files = sorted(
        path for path in raw.rglob("*") if path.is_file() and path.name != "SHA256SUMS"
    )
    lines = [f"{sha256(path)}  {path.relative_to(raw).as_posix()}" for path in files]
    path = raw / "SHA256SUMS"
    atomic_write_bytes(path, ("\n".join(lines) + "\n").encode())
    return path


def verify_sha256sums(repo_root: Path) -> tuple[str, ...]:
    """Re-hash every raw file attested by ``data/raw/SHA256SUMS``.

    This check complements the nClimGrid manifest: snapshots include GHCN,
    HOMR, and geometry inputs that do not share its two-column version-file
    structure.  Missing checksum files are an error rather than an invitation
    to trust archive metadata.
    """

    raw = Path(repo_root) / "data/raw"
    checksum_file = raw / "SHA256SUMS"
    if not checksum_file.is_file():
        return ("missing data/raw/SHA256SUMS",)
    expected: dict[str, str] = {}
    drift: list[str] = []
    for line_number, line in enumerate(checksum_file.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64 or not relative:
            drift.append(f"invalid SHA256SUMS line {line_number}")
            continue
        if relative in expected:
            drift.append(f"duplicate SHA256SUMS path {relative}")
            continue
        expected[relative] = digest
    actual = {
        path.relative_to(raw).as_posix(): path
        for path in raw.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    for relative, digest in expected.items():
        path = actual.get(relative)
        if path is None:
            drift.append(f"missing {relative}")
        elif sha256(path) != digest:
            drift.append(f"sha256 {relative}")
    for relative in sorted(actual.keys() - expected.keys()):
        drift.append(f"unlisted {relative}")
    return tuple(sorted(drift))


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _write_rows(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    with temp.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(rows[0]), extrasaction="raise")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["year_month"]))
    temp.replace(path)


def _check_rows(rows: list[dict[str, str]], donor_root: Path) -> list[str]:
    drift: list[str] = []
    for row in rows:
        for path_key, hash_key in (
            ("local_path", "sha256"),
            ("version_local_path", "version_sha256"),
        ):
            path = donor_root / "data" / row[path_key]
            if not path.is_file():
                drift.append(f"missing {row[path_key]}")
            elif sha256(path) != row[hash_key]:
                drift.append(f"sha256 {row[path_key]}")
    return drift


def _version_created_on(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if "downloaded on " in line:
            return line.split("downloaded on ", 1)[1].strip()
    return ""


def _vintage_id(repo_root: Path) -> str:
    path = repo_root / "config/data_vintage.yaml"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("nclimgrid_tavg:") and "id:" in line:
                return line.split("id:", 1)[1].strip()
    return "nclimgrid-daily_v1-0-0"


def _validate_members(archive: tarfile.TarFile, root: Path) -> None:
    root_text = f"{root}/"
    for member in archive.getmembers():
        target = (root / member.name).resolve()
        if not str(target).startswith(root_text) or member.issym() or member.islnk():
            raise NClimGridError(f"Unsafe snapshot member: {member.name}")
