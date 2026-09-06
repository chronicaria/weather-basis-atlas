#!/usr/bin/env python3
"""Derive a presentation-only release lock from an accepted lock.

Copies every scientific pin unchanged -- accepted artifacts, public source,
V1 archive, scientific configuration identity, scenario sets, model specs and
data vintages -- and recomputes only the file digests that record the code as
it stands: the presentation sources and, when a Python file has changed, the
``research.source_hashes`` inventory.  Nothing scientific is rerun or
relabelled; a bundle built from the result serves the same public data with
new templates, styles and scripts.

Refuses to write a lock whose scientific identity differs from the base.

    uv run python scripts/presentation_lock.py \
        --base config/releases/v2-candidate.lock.json \
        --out config/releases/v2.1-presentation.lock.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from weather_basis.provenance.ids import canonical_json, file_sha256

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ("d3.v7.9.0.min.js", "topojson-client.v3.1.0.min.js", "counties-albers-10m.json")
PINNED_SCIENCE = (
    "scientific_config_id",
    "scenario_set_ids",
    "model_spec_ids",
    "data_vintage_ids",
    "configuration_hashes",
    "scope",
)


def _digest_tree(root: Path, folder: str) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in sorted((root / folder).rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store"
    }


def presentation_hashes(root: Path) -> dict[str, str]:
    hashes = {
        **_digest_tree(root, "apps/site"),
        **_digest_tree(root, "src/weather_basis/publishing"),
        "uv.lock": file_sha256(root / "uv.lock"),
    }
    for filename in VENDOR:
        vendor = root / "web/vendor" / filename
        if not vendor.is_file():
            vendor = root / "site/assets/vendor" / filename
        hashes[vendor.relative_to(root).as_posix()] = file_sha256(vendor)
    return hashes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    base = json.loads(args.base.read_text())
    lock = json.loads(args.base.read_text())

    lock["presentation"] = {
        "base_path": base["presentation"]["base_path"],
        "source_hashes": presentation_hashes(ROOT),
    }
    lock["research"] = {
        **base["research"],
        "source_hashes": {
            path: digest
            for path, digest in _digest_tree(ROOT, "src/weather_basis").items()
            if path.endswith(".py")
        },
    }

    for field in PINNED_SCIENCE:
        assert lock["research"].get(field) == base["research"].get(field), field
    for field in ("artifacts", "public_source", "legacy_bundle", "route_map"):
        assert lock.get(field) == base.get(field), field

    args.out.write_text(canonical_json(lock) + "\n")
    changed = {
        section: sorted(
            path
            for path, digest in lock[section]["source_hashes"].items()
            if base[section]["source_hashes"].get(path) != digest
        )
        for section in ("presentation", "research")
    }
    print(
        json.dumps(
            {"out": str(args.out), "scientific_identity": "unchanged", "changed": changed}, indent=1
        )
    )


if __name__ == "__main__":
    main()
