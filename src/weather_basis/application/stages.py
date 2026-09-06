"""One canonical stage/dependency registry shared by CLI and maintenance docs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StageDefinition:
    stage_id: str
    dependencies: tuple[str, ...]
    producer_paths: tuple[str, ...]
    config_fields: tuple[str, ...]
    handler: Callable[[Any, Path], Sequence[Path] | None]
    description: str = ""
    selectors: tuple[str, ...] = ()


def _handler(name):
    from .handlers import dispatch_stage

    return partial(dispatch_stage, name)


def stage_registry(root: Path | None = None) -> dict[str, StageDefinition]:
    """Producer closures include domain code, schema and serialization semantics."""
    base = root or Path.cwd()
    shared = ("src/weather_basis/schemas/base.py", "src/weather_basis/provenance/ids.py")
    definitions = [
        (
            "inputs.audit",
            (),
            ("contracts", "schemas/vintages.py"),
            (),
            "Verify pinned source support and rights",
            (),
        ),
        (
            "panels.prepare",
            ("inputs.audit",),
            ("indices", "ingest"),
            ("pairs",),
            "Validate frozen panels/indexes",
            ("pairs",),
        ),
        (
            "atlas.evaluate",
            ("panels.prepare",),
            ("hedge",),
            ("pairs", "first_test_year", "last_test_year", "min_train", "he_convention"),
            "Causal decisions and exact matched historical support",
            ("pairs",),
        ),
        (
            "atlas.select_asof",
            ("atlas.evaluate",),
            ("hedge", "contracts/windows.py"),
            ("valuation_asof", "horizon_start", "horizon_end"),
            "Explicit current station decision",
            ("pairs",),
        ),
        (
            "models.fit",
            ("panels.prepare",),
            ("models", "application/models.py", "scenarios/r2j_production.py"),
            ("training_window", "min_train", "valuation_asof"),
            "Exact-cutoff immutable model fits",
            (),
        ),
        (
            "tournament.execute",
            ("models.fit",),
            (
                "models",
                "scenarios",
                "application/models.py",
                "config/research/experiments-v2.yaml",
                "config/research/r04-common-scenarios.yaml",
                "results/v2/experiments/R04-v3-corrected",
            ),
            ("seed", "training_window", "offline_paths"),
            "Registered representative/full model comparisons",
            ("origins",),
        ),
        (
            "models.select",
            ("tournament.execute",),
            (
                "models",
                "scenarios",
                "application/models.py",
                "config/research/experiments-v2.yaml",
                "config/research/r04-common-scenarios.yaml",
            ),
            ("scenario_generator",),
            "Accept a scenario specification from registered evidence",
            (),
        ),
        (
            "scenarios.build",
            ("models.select", "models.fit"),
            ("scenarios", "schemas/scenarios.py", "application/models.py"),
            (
                "scenario_generator",
                "seed",
                "offline_paths",
                "public_paths",
                "valuation_asof",
                "horizon_start",
                "horizon_end",
            ),
            "One horizon and aligned location/path identities",
            ("county_panel",),
        ),
        (
            "payoffs.build",
            ("scenarios.build",),
            (
                "portfolio",
                "schemas/portfolios.py",
                "application/portfolios.py",
                "research/publishing.py",
                "config/books",
            ),
            ("currency", "loss_convention"),
            "Closed DSL aligned cash-flow columns",
            (),
        ),
        (
            "quotes.build",
            ("payoffs.build", "atlas.select_asof", "scenarios.build"),
            ("pricing/v2.py", "portfolio/risk.py", "application/public_release.py"),
            ("tail_level", "currency"),
            "Physical and loaded price components with availability",
            ("pairs", "county_panel"),
        ),
        (
            "portfolios.evaluate",
            ("payoffs.build", "scenarios.build"),
            ("portfolio", "application/portfolios.py", "research/publishing.py", "config/books"),
            ("tail_level", "loss_convention", "currency"),
            "Signed loss ledger and feasible baselines",
            (),
        ),
        (
            "portfolios.optimize",
            ("portfolios.evaluate", "payoffs.build", "scenarios.build"),
            ("portfolio", "application/portfolios.py", "research/publishing.py", "config/books"),
            ("tail_level", "currency"),
            "Actual constrained objectives and implemented lots",
            (),
        ),
        (
            "cases.build",
            (
                "quotes.build",
                "portfolios.optimize",
                "scenarios.build",
                "atlas.evaluate",
                "atlas.select_asof",
            ),
            (
                "research/run.py",
                "research/evidence_surfaces.py",
                "publishing/projections.py",
                "application/public_release.py",
                "research/publishing.py",
                "config/books",
                "config/research/experiments-v2.yaml",
                "config/research/r04-common-scenarios.yaml",
            ),
            ("tail_level", "equivalence_bands"),
            "Research, cases, memo and export projections",
            (),
        ),
        (
            "site.build",
            ("cases.build",),
            ("publishing", "application/publishing.py", "application/public_release.py"),
            (),
            "Fresh public static bundle from accepted artifacts",
            (),
        ),
        (
            "research.next_station",
            ("cases.build",),
            (
                "research/next_station.py",
                "application/research.py",
                "config/research/next-station-v2.yaml",
            ),
            ("tail_level", "equivalence_bands"),
            "Bounded extra-station research pilot",
            (),
        ),
        (
            "release.verify",
            ("site.build",),
            ("publishing", "application/publishing.py", "application/public_release.py"),
            (),
            "Seal, identity, route and provenance validation",
            (),
        ),
    ]
    result = {}
    for name, dependencies, producers, fields, description, selectors in definitions:
        files = list(shared)
        files.append("src/weather_basis/application/handlers.py")
        for producer in producers:
            path = base / producer
            if not path.exists():
                path = base / "src/weather_basis" / producer
            if path.is_dir():
                files.extend(
                    str(p.relative_to(base))
                    for p in sorted(path.rglob("*"))
                    if p.is_file() and "__pycache__" not in p.parts
                )
            else:
                files.append(str(path.relative_to(base)))
        if name in ("site.build", "release.verify"):
            files.extend(
                str(p.relative_to(base))
                for p in sorted((base / "apps/site").rglob("*"))
                if p.is_file()
            )
        result[name] = StageDefinition(
            name,
            dependencies,
            tuple(sorted(set(files))),
            fields,
            _handler(name),
            description,
            selectors,
        )
    return result


def validate_selectors(request, definition: StageDefinition) -> None:
    """Reject selectors that a stage would otherwise ignore."""
    values = {
        "pairs": request.pairs,
        "origins": request.origins,
        "county_panel": request.county_panel,
    }
    ignored = [name for name, value in values.items() if value and name not in definition.selectors]
    if ignored:
        raise ValueError(
            f"stage {definition.stage_id} does not support selector(s): {', '.join(ignored)}"
        )
    duplicates = [name for name, value in values.items() if len(value) != len(set(value))]
    if duplicates:
        raise ValueError(f"duplicate selector values: {', '.join(duplicates)}")
