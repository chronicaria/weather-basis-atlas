"""Static renderer and lightweight site checks."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt

from weather_basis.io import atomic_write_bytes, gzip_bytes
from weather_basis.site.payloads import build_payloads
from weather_basis.site.provenance import validate_provenance

PAGES = ("index", "methodology", "about", "nebraska", "404")


def _metric_from_results(root: Path, dotted: str, fmt: str | None = None) -> str:
    """Resolve a documented metric slot without giving a result a made-up fallback."""
    parts = dotted.split(".")
    path = root / "results" / (parts[0] + ".json")
    if not path.exists():
        path = root / "results/atlas/headline.json"
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
        for part in parts[1:] if path.name == parts[0] + ".json" else parts:
            value = value[part]
        return format(value, fmt or "") if isinstance(value, (int, float)) else str(value)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return "not yet computed"


def build_site(root: Path, out: Path, config: Any | None = None) -> dict[str, Any]:
    root, out = Path(root), Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    templates = root / "web/templates"
    env = Environment(
        loader=FileSystemLoader(templates), autoescape=select_autoescape(("html", "xml"))
    )
    markdown = MarkdownIt("commonmark", {"html": False})
    for name in PAGES:
        template = env.get_template(f"{name}.html.j2")
        document = root / f"docs/site/{name}.md"
        content = markdown.render(document.read_text(encoding="utf-8")) if document.exists() else ""
        rendered = template.render(
            content=content, metric=lambda key, fmt=None: _metric_from_results(root, key, fmt)
        )
        (out / f"{name}.html").write_text(rendered, encoding="utf-8")
    for source in (root / "web/static", root / "web/vendor"):
        if source.exists():
            shutil.copytree(source, out / "assets" / source.name, dirs_exist_ok=True)
    stats = build_payloads(root, out, config)
    _write_results_csv(root, out)
    schema = root / "src/weather_basis/schemas"
    if schema.exists():
        shutil.copytree(schema, out / "schema", dirs_exist_ok=True)
    validate_payload_schemas(out)
    (out / ".nojekyll").touch()
    stats["site_bytes"] = sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
    return stats


def _write_results_csv(root: Path, out: Path) -> None:
    """Ship a compact, deterministic public extract when the atlas table exists."""
    path = root / "results/atlas/pairs.parquet"
    if not path.exists():
        return
    import pandas as pd

    table = pd.read_parquet(path)
    numeric = table.select_dtypes(include="number").columns
    table.loc[:, numeric] = table.loc[:, numeric].round(4)
    atomic_write_bytes(out / "data/results.csv.gz", gzip_bytes(table.to_csv(index=False).encode()))


def validate_payload_schemas(out: Path) -> None:
    """Validate uncompressed payloads against the schemas copied beside them."""
    names = {
        "meta": "meta.schema.json",
        "counties": "counties.schema.json",
        "stations": "stations.schema.json",
    }
    for stem, schema_name in names.items():
        payload, schema = out / f"data/{stem}.json", out / f"schema/{schema_name}"
        if payload.exists() and schema.exists():
            Draft202012Validator(json.loads(schema.read_text())).validate(json.loads(payload.read_text()))
    summary_schema = out / "schema/summary.schema.json"
    if summary_schema.exists():
        validator = Draft202012Validator(json.loads(summary_schema.read_text()))
        for payload in (out / "data/summary").glob("*.json"):
            validator.validate(json.loads(payload.read_text()))


def check_site(
    root: Path, out: Path, config: Any | None = None, *, release: bool = False
) -> list[str]:
    root, out = Path(root), Path(out)
    errors = validate_provenance(root, release=release)
    if not out.exists():
        return [*errors, "site directory does not exist"]
    site_cfg = getattr(config, "site", {}) if config is not None else {}
    maximum = (
        getattr(site_cfg, "file_max_mb", 5)
        if not isinstance(site_cfg, dict)
        else site_cfg.get("file_max_mb", 5)
    )
    for path in out.rglob("*"):
        if path.is_file() and path.stat().st_size > int(maximum * 1024 * 1024):
            errors.append(f"oversize file: {path}")
    counties = out / "data/counties.json"
    if counties.exists():
        for row in json.loads(counties.read_text()):
            if not (out / f"data/county/{row['fips']}.json.gz").exists():
                errors.append(f"missing county payload: {row['fips']}")
    return errors
