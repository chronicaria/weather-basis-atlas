#!/usr/bin/env python3
"""Materialize a fresh public source from an accepted core and B26 artifact.

This release leaf reuses every core object byte. It adds one identified research
case and never executes numerical stages or changes the accepted core source.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
from pathlib import Path

from weather_basis.provenance.ids import canonical_json, content_id, file_sha256
from weather_basis.publishing.projections import envelope


def materialize(core: Path, pilot: Path, out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"Release source must be fresh: {out}")
    blueprint = json.loads(core.read_text())
    report = json.loads((pilot / "next_station_report.json").read_text())
    manifest = json.loads((pilot / "artifact-manifest.json").read_text())
    for item in manifest["files"]:
        if file_sha256(pilot / item["path"]) != item["sha256"]:
            raise ValueError("Station pilot artifact bytes do not match their manifest")
    out.mkdir(parents=True)
    for ref in blueprint["objects"].values():
        relative = Path(ref["source_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe core public object path")
        source, target = core.parent / relative, out / relative
        if file_sha256(source) != ref["sha256"]:
            raise ValueError("Core public object hash mismatch")
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    context = blueprint["bootstrap"]["scenario_sets"][0]
    record = envelope(
        release_id="candidate", result_type="research_evidence", payload=report,
        analysis_id=manifest["analysis_id"],
        source_artifact_ids=(manifest["artifact_id"], report["protocol_id"]),
        data_vintage_id=context["data_vintage_id"], model_spec_ids=(), scenario_set_id=None,
        valuation_asof="2026-07-01", index_definition_id="HDD-01",
        units="USD losses and USD-squared variance; see named metrics", currency="USD",
        evidence_reference="B26 frozen-origin Nebraska study; source and protocol in case tables.",
    )
    path = out / "public-records" / f"{record.object_id.replace(':', '-')}.json.gz"
    path.write_bytes(gzip.compress((canonical_json(record.to_dict()) + "\n").encode(), mtime=0))
    blueprint["objects"]["research:next_station"] = {
        "source_path": str(path.relative_to(out)), "sha256": file_sha256(path)
    }
    target = out / "public-source.json"
    target.write_text(canonical_json(blueprint) + "\n")
    supplement = {
        "schema_version": "2.0", "kind": "accepted-core-plus-station-pilot-release-leaf",
        "core_source": str(core), "core_source_sha256": file_sha256(core),
        "pilot_directory": str(pilot), "pilot_artifact_id": manifest["artifact_id"],
        "pilot_protocol_id": report["protocol_id"], "pilot_disposition": report["disposition"],
        "reused_core_objects": len(blueprint["objects"]) - 1,
        "added_object": blueprint["objects"]["research:next_station"],
        "public_source_sha256": file_sha256(target),
    }
    supplement["artifact_id"] = content_id(supplement, prefix="release-source")
    (out / "supplement-manifest.json").write_text(canonical_json(supplement) + "\n")
    return supplement


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-source", type=Path, required=True)
    parser.add_argument("--pilot-directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(materialize(args.core_source, args.pilot_directory, args.out), sort_keys=True))
