"""Plan Section 2.1: enforce the package import-boundary allowlist with AST."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = _ROOT / "src" / "weather_basis"
_ALLOWED = {
    "config": set(),
    "io": set(),
    "manifest": set(),
    "manifest_stage": {"config", "io", "manifest"},
    "http": set(),
    "contracts": {"config", "schemas"},
    "ingest": {"config", "io", "manifest", "http", "contracts"},
    "indices": {"config", "io", "manifest", "contracts", "ingest.panel"},
    "hedge": {"config", "io", "manifest", "contracts", "indices", "provenance"},
    "models": {"config", "io", "manifest", "contracts", "indices", "provenance"},
    "pricing": {
        "config",
        "io",
        "manifest",
        "contracts",
        "hedge.asof",
        "hedge.policies",
        "portfolio.payoffs",
        "provenance",
    },
    "site": {
        "config",
        "io",
        "manifest",
        "contracts",
        "pricing.distribution",
        "pricing.coherence",
        "schemas",
    },
    "validation": {"*"},
    "cli": {"*"},
    # V2 layers.  The application package is the only orchestration boundary;
    # domain packages remain unable to import it or the CLI.
    "application": {
        "contracts.calendar",
        "execution",
        "hedge",
        "portfolio",
        "pricing",
        "provenance",
        "publishing",
        "research",
        "scenarios",
        "schemas",
    },
    "execution": {"provenance"},
    "provenance": set(),
    "scenarios": {"contracts", "models", "provenance", "schemas"},
    "portfolio": set(),
    "publishing": {"provenance", "schemas"},
    "research": {"contracts", "portfolio", "provenance", "publishing", "schemas"},
    "schemas": {"provenance"},
}


def _owner(path: Path) -> str:
    relative = path.relative_to(_SOURCE)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    package = ".".join(("weather_basis", *path.relative_to(_SOURCE).parent.parts))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name for alias in node.names if alias.name.startswith("weather_basis")
            )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imported = resolve_name("." * node.level + (node.module or ""), package)
                if imported.startswith("weather_basis"):
                    found.append(imported)
            elif node.module and node.module.startswith("weather_basis"):
                found.append(node.module)
    return found


def _permitted(owner: str, imported: str) -> bool:
    if imported == "weather_basis":
        return True
    target = imported.removeprefix("weather_basis.")
    if target == owner or target.startswith(f"{owner}."):
        return True
    allowed = _ALLOWED[owner]
    return "*" in allowed or any(
        target == item or target.startswith(f"{item}.") for item in allowed
    )


def test_internal_imports_match_the_section_2_1_allowlist() -> None:
    """Plan Section 2.1: subpackages import only their declared dependencies."""

    violations = [
        f"{path.relative_to(_ROOT)} imports {imported}"
        for path in _SOURCE.rglob("*.py")
        for imported in _imports(path)
        if not _permitted(_owner(path), imported)
    ]
    assert not violations, "\n".join(violations)
