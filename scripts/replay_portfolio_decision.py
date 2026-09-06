#!/usr/bin/env python3
"""Verify a browser decision and independently revalue its frozen USD ledger.

No weather download, simulation or optimization occurs. The saved positions
are evaluated in Python against the exact finite problem inside the manifest.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
from pathlib import Path

import numpy as np

from weather_basis.portfolio.ledger import PortfolioProblem, deterministic_cost, residual_loss
from weather_basis.portfolio.optimize import _constraint_residuals
from weather_basis.portfolio.risk import risk_statistics
from weather_basis.provenance.ids import file_sha256

IDENTITY_SCRIPT = r"""
const fs = require('node:fs'), crypto = require('node:crypto'), vm = require('node:vm');
const record = JSON.parse(fs.readFileSync(0, 'utf8'));
const canonical = (v) => Array.isArray(v) ? '[' + v.map(canonical).join(',') + ']'
  : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map(k => JSON.stringify(k)
  + ':' + canonical(v[k])).join(',') + '}' : JSON.stringify(v);
const unsigned = {...record}; delete unsigned.decision_id;
globalThis.self = globalThis;
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
process.stdout.write(JSON.stringify({decision_id: 'decision:' + crypto.createHash('sha256')
  .update(canonical(unsigned)).digest('hex'),
  input_hash: WbaPortfolio.stableHash(record.request.problem)}));
"""


def replay(path: Path) -> dict:
    root = Path(__file__).resolve().parents[1]
    raw = path.read_text()
    record = json.loads(raw)
    identities = json.loads(subprocess.run(
        ["node", "-e", IDENTITY_SCRIPT, str(root / "apps/site/js/kernels/portfolio.js")],
        input=raw, text=True, capture_output=True, check=True,
    ).stdout)
    if identities["decision_id"] != record["decision_id"]:
        raise ValueError("Saved decision SHA-256 identity does not match")
    request = record["request"]
    if identities["input_hash"] != request["input_hash"]:
        raise ValueError("Saved compiled problem does not match its input identity")
    raw_problem = request["problem"]
    fields = {field.name for field in dataclasses.fields(PortfolioProblem)}
    unknown = set(raw_problem) - fields - {"currency", "units", "scenario_set_id", "schema_version"}
    if unknown:
        raise ValueError(f"Unsupported problem fields: {sorted(unknown)}")
    problem = PortfolioProblem(**{
        key: value for key, value in raw_problem.items() if key in fields
    })
    positions = np.asarray(record["result"]["positions"], dtype=float)
    loss = residual_loss(problem, positions)
    risk = dataclasses.asdict(risk_statistics(loss, problem.weights, alpha=0.90))
    cost = deterministic_cost(problem, positions)
    result = record["result"]
    if not np.allclose(loss, result["residual_loss"], rtol=1e-10, atol=1e-6):
        raise ValueError("Python residual losses differ from the accepted decision")
    if not np.isclose(cost, result["deterministic_cost"], rtol=1e-10, atol=1e-6):
        raise ValueError("Python deterministic cost differs from the accepted decision")
    for name in ("mean", "variance", "expected_shortfall"):
        if not np.isclose(risk[name], result["risk"][name], rtol=1e-9, atol=1e-6):
            raise ValueError(f"Python {name} differs from the accepted decision")
    constraints = _constraint_residuals(problem, positions)
    if any(value < -1e-6 for value in constraints.values()):
        raise ValueError("Saved positions violate a declared constraint")
    if request.get("lots") and not np.allclose(
        positions / problem.lot_sizes, np.round(positions / problem.lot_sizes), atol=1e-6
    ):
        raise ValueError("Saved positions do not satisfy the declared contract lots")
    return {
        "status": "passed", "scope": "independent frozen-position replay; no reoptimization",
        "decision_id": record["decision_id"], "decision_file_sha256": file_sha256(path),
        "release_id": record["release_id"], "scenario_set_id": record["scenario_set_id"],
        "scenarios": len(problem.scenario_ids),
        "source_artifact_ids": record["source_artifact_ids"],
        "positions": positions.tolist(), "deterministic_cost": cost, "risk": risk,
        "maximum_residual_difference": float(np.max(np.abs(loss - result["residual_loss"]))),
        "constraint_residuals": {
            key: float(value) if np.isfinite(value) else None for key, value in constraints.items()
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decision", type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.decision), sort_keys=True, allow_nan=False))
