"""Fresh static site assembly from pinned V2 projections; never refits weather."""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from weather_basis.provenance.ids import canonical_json, file_sha256
from weather_basis.publishing.projections import validate_bootstrap, write_public_data
from weather_basis.schemas.base import require
from weather_basis.schemas.public import ResultEnvelope

ROUTES = {
    "explore": "index.html",
    "compare": "compare.html",
    "contract": "contract.html",
    "portfolio": "portfolio.html",
    "research": "research/index.html",
}


def _source(root: Path, path: str) -> Path:
    result = Path(path)
    return result if result.is_absolute() else root / result


def build_site(*, root: Path, out: Path, release_id: str, lock: dict[str, Any]) -> dict[str, Any]:
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    require(not any(out.iterdir()), "Site build requires an empty destination")
    source = root / "apps/site"
    require(source.is_dir(), "Missing V2 frontend source")
    node = shutil.which("node")
    require(node is not None, "Node.js is required to validate browser modules before release")
    for module in sorted((source / "js").rglob("*.js")):
        # Force module parsing on stdin: Node's automatic file-mode detection
        # can return success without reporting a syntax error in an ES module.
        parsed = subprocess.run(
            [node, "--input-type=module", "--check"],
            input=module.read_text(),
            text=True,
            capture_output=True,
            check=False,
        )
        require(parsed.returncode == 0, f"Invalid browser module {module}: {parsed.stderr}")
    public_out = out / "data/v2/releases" / release_id
    if lock.get("public_source"):
        blueprint_path = _source(root, lock["public_source"])
        payload = json.loads(blueprint_path.read_text())
        require(set(payload) == {"bootstrap", "objects"}, "Invalid public projection source")
        bootstrap = {**payload["bootstrap"], "release_id": release_id, "route_map": ROUTES}

        def records():
            for key, value in sorted(payload["objects"].items()):
                if "source_path" in value:
                    require(set(value) == {"source_path", "sha256"}, "Invalid source reference")
                    relative = Path(value["source_path"])
                    require(
                        not relative.is_absolute() and ".." not in relative.parts,
                        "Unsafe public source record path",
                    )
                    path = blueprint_path.parent / relative
                    require(file_sha256(path) == value["sha256"], "Public source hash mismatch")
                    raw = (
                        gzip.decompress(path.read_bytes())
                        if path.suffix == ".gz"
                        else path.read_bytes()
                    )
                    value = json.loads(raw)
                yield key, replace(ResultEnvelope.from_dict(value), release_id=release_id)

        objects = records()
        bootstrap = write_public_data(public_out, bootstrap=bootstrap, objects=objects)
    elif lock.get("public_data"):
        public_source = _source(root, lock["public_data"])
        bootstrap = json.loads((public_source / "bootstrap.json").read_text())
        validate_bootstrap(bootstrap)
        require(bootstrap["release_id"] == release_id, "Pinned public data has different release")
        shutil.copytree(public_source, public_out)
    else:
        raise FileNotFoundError("release requires pinned public_source or public_data")
    (out / "data/v2/current.json").write_text(
        canonical_json({"schema_version": "2.0", "release_id": release_id}) + "\n"
    )
    for route in ROUTES.values():
        template = source / "templates" / route
        require(template.is_file(), f"Missing route source {route}")
        target = out / route
        target.parent.mkdir(parents=True, exist_ok=True)
        html = template.read_text()
        html = html.replace("__WBA_RELEASE_ID__", release_id)
        target.write_text(html)
    for folder in ("js", "styles", "vendor"):
        if (source / folder).is_dir():
            shutil.copytree(source / folder, out / folder)
    vendor = out / "assets/vendor"
    vendor.mkdir(parents=True)
    for filename in (
        "d3.v7.9.0.min.js",
        "topojson-client.v3.1.0.min.js",
        "counties-albers-10m.json",
    ):
        src = root / "web/vendor" / filename
        if not src.is_file():
            src = root / "site/assets/vendor" / filename
        require(src.is_file(), f"Missing pinned map vendor artifact {filename}")
        shutil.copyfile(src, vendor / filename)
    legacy = lock.get("legacy_bundle")
    if legacy:
        legacy_root = _source(root, legacy)
        require((legacy_root / "index.html").is_file(), "Missing preserved V1 bundle")
        shutil.copytree(legacy_root, out / "v1")
    # Legacy document routes remain explicit archival destinations, never new figures under old IDs.
    for filename in ("methodology.html", "model-card.html", "nebraska.html", "about.html"):
        target = out / filename
        target.write_text(
            "<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>V1 archive · Weather Basis Atlas</title><h1>V1 research archive</h1>"
            f"<p>This link identifies the original V1 research release. "
            f"<a href='v1/{filename}'>Open the preserved V1 page</a> or "
            "<a href='research/index.html'>read the V2 evidence</a>.</p></html>"
        )
    (out / ".nojekyll").write_text("")
    return {
        "schema_version": "2.0",
        "release_id": release_id,
        "route_map": ROUTES,
        "objects": bootstrap.get("object_count", len(bootstrap["objects"])),
        "counties": len(bootstrap["county_registry"]),
    }
