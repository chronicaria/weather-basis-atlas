"""Command-line interface for Weather Basis Atlas."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wba", description="Build the Weather Basis Atlas")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("data", "contracts", "indices", "atlas", "models", "quotes", "nebraska", "site", "reproduce", "gate"):
        sub.add_parser(name)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
