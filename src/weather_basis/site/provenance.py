"""No-fabrication scans used by the static-site build."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN_LITERALS = tuple(f"{number}%" for number in (46, 31, 58, 29)) + (
    "[31" + "%, 58" + "%]",
    "[31" + "%,58" + "%]",
)
SOURCE_ROOTS = ("web/templates", "web/static", "docs/site", "docs/preregistration.md", "src")


def source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for name in SOURCE_ROOTS:
        path = root / name
        if path.is_file():
            files.append(path)
        elif path.exists():
            files.extend(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix in {".py", ".js", ".css", ".j2", ".md"}
            )
    return files


def forbidden_literals(root: Path) -> list[str]:
    hits: list[str] = []
    for path in source_files(root):
        contents = path.read_text(encoding="utf-8", errors="ignore")
        for literal in FORBIDDEN_LITERALS:
            if literal in contents:
                hits.append(f"{path.relative_to(root)}: {literal}")
    return hits


def metric_sources(root: Path) -> list[str]:
    missing: list[str] = []
    pattern = re.compile(r"<[^>]*data-metric(?:\s|=)[^>]*>", re.I)
    site = root / "site"
    for path in site.rglob("*.html") if site.exists() else []:
        for tag in pattern.findall(path.read_text(encoding="utf-8")):
            if "data-source=" not in tag:
                missing.append(str(path.relative_to(root)))
    return missing


def external_urls(root: Path) -> list[str]:
    hits: list[str] = []
    scripts = root / "web/static/js"
    for path in scripts.rglob("*.js") if scripts.exists() else []:
        if re.search(r"https?://", path.read_text(encoding="utf-8")):
            hits.append(str(path.relative_to(root)))
    return hits


def validate_provenance(root: Path, *, release: bool = False) -> list[str]:
    errors = forbidden_literals(root) + metric_sources(root) + external_urls(root)
    site = root / "site"
    if release and site.exists():
        for path in site.rglob("*"):
            if path.is_file() and "not yet computed" in path.read_text(
                encoding="utf-8", errors="ignore"
            ).lower():
                errors.append(f"{path.relative_to(root)}: unresolved metric")
    return errors
