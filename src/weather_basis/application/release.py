"""Application boundary for V2 release construction and recovery."""

from __future__ import annotations

from pathlib import Path

from weather_basis.publishing.release import (
    build_release,
    inspect_release,
    rollback_release,
    verify_release,
)


def build(*, root: Path, lock_path: Path, out: Path) -> dict[str, object]:
    return build_release(root, lock_path, out)


def verify(*, bundle: Path) -> dict[str, object]:
    return verify_release(bundle)


def inspect(*, bundle: Path) -> dict[str, object]:
    return inspect_release(bundle)


def rollback(*, bundle: Path, target: Path) -> dict[str, object]:
    return rollback_release(bundle, target)
