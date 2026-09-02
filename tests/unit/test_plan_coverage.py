"""Plan Section 12.4: every required plan section is named by a test docstring."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED = {
    "4.3",
    "4.5",
    "4.7",
    "5.2",
    "5.3",
    "6.2",
    "6.3",
    "6.4",
    "6.5",
    "7.2",
    "7.3",
    "7.4",
    "7.5",
    "8.1",
    "8.3",
    "8.4",
    "9.4",
    "13",
}


def _test_docstrings() -> list[str]:
    docstrings: list[str] = []
    for path in (_ROOT / "tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_docstring = ast.get_docstring(tree)
        if module_docstring:
            docstrings.append(module_docstring)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                docstring = ast.get_docstring(node)
                if docstring:
                    docstrings.append(docstring)
    return docstrings


def test_required_plan_sections_have_a_documented_test() -> None:
    """Plan Section 12.4: coverage is asserted from test/module docstrings, not filenames."""

    covered = set(re.findall(r"(?<!\d)(?:[4-9]\.\d|13)(?!\d)", "\n".join(_test_docstrings())))
    assert not (missing := _REQUIRED - covered), (
        f"missing documented plan sections: {sorted(missing)}"
    )
