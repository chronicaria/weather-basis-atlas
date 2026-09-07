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


def _legacy_stub(archived: str, title: str, heading: str | None = None) -> str:
    """A styled signpost for a V1 URL: the archived page is preserved, not current."""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · V1 archive · Weather Basis Atlas</title>
<link rel="stylesheet" href="styles/tokens.css">
<link rel="stylesheet" href="styles/layout.css">
<link rel="stylesheet" href="styles/components.css"></head>
<body><header class="masthead"><div class="masthead-inner">
<a class="wordmark" href="index.html">Weather <em>Basis Atlas</em></a>
<nav class="primary-nav" aria-label="Primary">
<a href="index.html">Explore</a>
<a href="compare.html">Compare</a>
<a href="contract.html">Contract Lab</a>
<a href="portfolio.html">Portfolio Lab</a>
<a href="research/index.html">Research</a></nav></div></header>
<main id="main"><div class="page-head"><div>
<p class="eyebrow">First edition archive</p>
<h1>{heading or f"{title} has moved."}</h1>
<p class="lede">This address belongs to the first edition of the atlas,
published in September 2026 and kept exactly as it was. Its station choices and
effectiveness figures were later re-measured on matched seasons and some of them
changed, and it shows modelled bid, mid and ask indications that the current
release does not publish. Read it as a record of what was said then, not as the
current result.</p>
</div></div>
<div class="btn-row">
<a class="btn btn-primary" href="research/index.html">Read the current research</a>
<a class="btn" href="v1/{archived}">Open the archived page</a>
<a class="btn btn-quiet" href="index.html">Go to the map</a></div></main>
<footer class="site-footer"><div class="site-footer-inner"><div>
<h4>Research and education only</h4>
<p>Model estimates built from public NOAA temperature records. Nothing here is
an executable quote, an offer, insurance, investment advice, or a promise of
hedge performance.</p></div></div></footer></body></html>
"""


def _not_found() -> str:
    """The page a mistyped or stale address lands on: say so, then offer the way in."""

    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Page not found · Weather Basis Atlas</title>
<link rel="stylesheet" href="/weather-basis-atlas/styles/tokens.css">
<link rel="stylesheet" href="/weather-basis-atlas/styles/layout.css">
<link rel="stylesheet" href="/weather-basis-atlas/styles/components.css"></head>
<body><header class="masthead"><div class="masthead-inner">
<a class="wordmark" href="/weather-basis-atlas/">Weather <em>Basis Atlas</em></a>
<nav class="primary-nav" aria-label="Primary">
<a href="/weather-basis-atlas/">Explore</a>
<a href="/weather-basis-atlas/compare.html">Compare</a>
<a href="/weather-basis-atlas/contract.html">Contract Lab</a>
<a href="/weather-basis-atlas/portfolio.html">Portfolio Lab</a>
<a href="/weather-basis-atlas/research/index.html">Research</a></nav></div></header>
<main id="main"><div class="page-head"><div>
<h1>Page not found.</h1>
<p class="lede">There is nothing at this address. The atlas has five places to
go, and the map is the usual way in.</p></div></div>
<div class="btn-row">
<a class="btn btn-primary" href="/weather-basis-atlas/">Go to the map</a>
<a class="btn" href="/weather-basis-atlas/compare.html">Compare counties</a>
<a class="btn" href="/weather-basis-atlas/contract.html">Contract Lab</a>
<a class="btn" href="/weather-basis-atlas/portfolio.html">Portfolio Lab</a>
<a class="btn" href="/weather-basis-atlas/research/index.html">Research</a></div>
<p class="mt-lg"><a href="/weather-basis-atlas/v1-archive.html">Looking for the
first edition of the atlas?</a></p></main>
<footer class="site-footer"><div class="site-footer-inner"><div>
<h4>Research and education only</h4>
<p>Model estimates built from public NOAA temperature records. Nothing here is
an executable quote, an offer, insurance, investment advice, or a promise of
hedge performance.</p></div></div></footer></body></html>
"""


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
    # Every shipped presentation byte must be pinned, or the release ID would not
    # identify the bytes it publishes.
    pinned = set(lock.get("presentation", {}).get("source_hashes", {}))
    if pinned:
        unpinned = sorted(
            path.relative_to(root).as_posix()
            for path in source.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.relative_to(root).as_posix() not in pinned
        )
        require(not unpinned, f"Unpinned presentation source: {', '.join(unpinned)}")
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
    for route, archived, title, heading in (
        ("methodology.html", "methodology.html", "Methodology", None),
        ("model-card.html", "model_card.html", "Model card", None),
        ("nebraska.html", "nebraska.html", "Nebraska case study", None),
        ("about.html", "about.html", "Provenance", None),
        # The footer's archive link lands here rather than inside the sealed V1 tree,
        # which cannot carry a banner of its own without breaking its pinned digest.
        ("v1-archive.html", "index.html", "The first edition", "The first edition of the atlas."),
    ):
        require((out / "v1" / archived).is_file(), f"Missing archived page v1/{archived}")
        (out / route).write_text(_legacy_stub(archived, title, heading))
    (out / "404.html").write_text(_not_found())
    (out / ".nojekyll").write_text("")
    return {
        "schema_version": "2.0",
        "release_id": release_id,
        "route_map": ROUTES,
        "objects": bootstrap.get("object_count", len(bootstrap["objects"])),
        "counties": len(bootstrap["county_registry"]),
    }
