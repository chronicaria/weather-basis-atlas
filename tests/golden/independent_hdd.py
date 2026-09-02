"""Dependency-free reference calculator for verbatim GHCN golden excerpts.

Usage: ``python tests/golden/independent_hdd.py excerpt.csv [...]``.  It is
deliberately independent of the package under test and prints one JSON object
per input, with both monthly HDD and CDD at the integer-Fahrenheit rulebook
precision.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path


def integer_f(tenths_c: str) -> int:
    value = float(tenths_c) / 10.0 * 9.0 / 5.0 + 32.0
    return math.floor(value + 0.5)


def blank_qflag(attributes: str | None) -> bool:
    parts = (attributes or "").split(",")
    return len(parts) < 2 or not parts[1].strip()


def index(path: Path) -> dict[str, object]:
    hdd = cdd = 0.0
    n_days = 0
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if not row.get("TMAX") or not row.get("TMIN"):
                continue
            if not blank_qflag(row.get("TMAX_ATTRIBUTES")) or not blank_qflag(
                row.get("TMIN_ATTRIBUTES")
            ):
                continue
            tbar = (integer_f(row["TMAX"]) + integer_f(row["TMIN"])) / 2.0
            hdd += max(65.0 - tbar, 0.0)
            cdd += max(tbar - 65.0, 0.0)
            n_days += 1
    return {"file": path.name, "n_days": n_days, "hdd": hdd, "cdd": cdd}


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print(json.dumps(index(Path(name)), sort_keys=True))
