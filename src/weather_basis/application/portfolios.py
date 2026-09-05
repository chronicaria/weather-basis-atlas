"""V2 portfolio-stage adapters consuming frozen aligned scenario artifacts only."""

from __future__ import annotations

import json
import math
from pathlib import Path

from weather_basis.provenance.ids import canonical_json, content_id
from weather_basis.research.publishing import compile_book, compile_sample_books


def _scenario_directory(context) -> Path:
    """Resolve a supplied B11 artifact from registered stage parents; never refit weather."""
    candidates: list[Path] = []
    for directory in context.dependency_directories.get("scenarios.build", []):
        if (directory / "manifest.json").is_file():
            candidates.append(directory)
        candidates.extend(path.parent for path in directory.rglob("manifest.json"))
    requested = context.request.get("scenario_artifact")
    if requested:
        requested_path = Path(requested)
        candidates.append(
            requested_path if requested_path.is_absolute() else context.root / requested_path
        )
    valid = []
    for candidate in candidates:
        manifest = candidate / "manifest.json"
        if (
            manifest.is_file()
            and json.loads(manifest.read_text()).get("kind")
            in {"bounded-common-scenario-artifact", "r2j-production-stream"}
        ):
            valid.append(candidate)
    unique = {path.resolve() for path in valid}
    if len(unique) != 1:
        raise FileNotFoundError(f"Expected one frozen B11 scenario artifact; found {len(unique)}")
    return next(iter(unique))


def _write(out: Path, name: str, value: object) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    target = out / name
    target.write_text(canonical_json(value) + "\n")
    return target


def _custom_book(context) -> dict[str, object] | None:
    """Load one caller supplied book and reject ambiguous/partial inputs."""
    book_path = context.request.get("book_path")
    if not book_path:
        return None
    source = Path(book_path)
    if not source.is_absolute():
        source = context.root / source
    if not source.is_file():
        raise FileNotFoundError(f"book_path does not exist: {source}")
    try:
        book = json.loads(source.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"book_path must contain a JSON object: {source}") from error
    if not isinstance(book, dict):
        raise ValueError("book_path must contain a JSON object")
    required = {"schema_version", "book_id", "objective", "tail_level", "holdings", "cost_policy"}
    missing = sorted(required - set(book))
    if missing:
        raise ValueError(f"custom book missing required fields: {', '.join(missing)}")
    if (
        book["schema_version"] != "2.0"
        or not isinstance(book["book_id"], str)
        or not book["book_id"]
    ):
        raise ValueError("custom book must have schema_version 2.0 and a non-empty book_id")
    if book["objective"] not in {"es", "min_cost_es", "variance", "mse"}:
        raise ValueError("custom book objective must be es, min_cost_es, variance, or mse")
    if book["objective"] == "min_cost_es" and not (
        isinstance(book.get("es_target"), (int, float))
        and math.isfinite(book["es_target"])
    ):
        raise ValueError("min_cost_es custom book requires finite numeric es_target")
    if not isinstance(book["tail_level"], (int, float)) or not 0 < book["tail_level"] < 1:
        raise ValueError("custom book tail_level must be in (0, 1)")
    if not isinstance(book["holdings"], list) or not book["holdings"]:
        raise ValueError("custom book must contain a non-empty holdings list")
    if not isinstance(book["cost_policy"], dict) or not isinstance(
        book["cost_policy"].get("contract_fee_usd"), (int, float)
    ) or book["cost_policy"]["contract_fee_usd"] < 0:
        raise ValueError("custom book cost_policy must specify non-negative contract_fee_usd")
    holding_fields = {
        "row_id", "kind", "entity_id", "fips", "pair", "amount", "budget", "loss_kind"
    }
    for row in book["holdings"]:
        if not isinstance(row, dict) or not holding_fields <= set(row):
            raise ValueError(
                "each custom holding needs row_id, kind, entity_id, fips, pair, amount, "
                "budget, and loss_kind"
            )
        if row["kind"] not in {"exposure", "claim"}:
            raise ValueError("custom holding kind must be exposure or claim")
    return book


def _objective_book(context, book: dict[str, object]) -> dict[str, object]:
    """Apply the stage request's optional objective without mutating the saved book."""
    requested = context.request.get("objective")
    if requested is None:
        return book
    if requested not in {"es", "min_cost_es", "variance", "mse"}:
        raise ValueError("requested objective must be es, min_cost_es, variance, or mse")
    if requested == "min_cost_es" and not (
        isinstance(book.get("es_target"), (int, float))
        and math.isfinite(book["es_target"])
    ):
        raise ValueError("min_cost_es request requires es_target in the book")
    return {**book, "objective": requested}


def _payoff_parent(context, scenario_dir: Path) -> dict[str, dict[str, object]] | None:
    """Reuse the already compiled payoffs artifact when it is the sole parent."""
    candidates: list[Path] = []
    for directory in context.dependency_directories.get("payoffs.build", []):
        candidates.extend(directory.rglob("portfolio_manifest.json"))
    unique = {path.resolve() for path in candidates}
    if not unique:
        return None
    if len(unique) != 1:
        raise ValueError("Expected one payoffs.build portfolio manifest")
    manifest = json.loads(next(iter(unique)).read_text())
    if Path(manifest.get("scenario_artifact", "")).resolve() != scenario_dir.resolve():
        raise ValueError("payoffs.build portfolio artifact uses a different scenario parent")
    books: dict[str, dict[str, object]] = {}
    for book_id in manifest.get("books", {}):
        path = next(iter(unique)).parent / f"{book_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"payoffs.build did not retain book result {book_id}")
        books[book_id] = json.loads(path.read_text())
    requested = context.request.get("objective")
    if requested and any(
        book.get("optimized", {}).get("objective") != requested for book in books.values()
    ):
        return None
    return books


def _zero_cost_sensitivity(
    context, scenario_dir: Path, book: dict[str, object]
) -> dict[str, object]:
    """Reprice an identical finite book with every deterministic hedge cost set to zero."""
    return compile_book(
        context.root,
        scenario_dir,
        book,
        cost_policy={"contract_fee_usd": 0.0, "zero_cost_sensitivity": True},
        constraints=book.get("constraints"),
    )


def _with_zero_cost_sensitivity(
    scientific_result: dict[str, object], sensitivity: dict[str, object]
) -> dict[str, object]:
    """Wrap immutable scientific output with app-only sensitivity and its own identity."""
    scientific_id = scientific_result["result_id"]
    result = {
        **scientific_result,
        "scientific_result_id": scientific_id,
        "zero_cost_sensitivity": sensitivity,
    }
    result.pop("result_id")
    result["result_id"] = content_id(result, prefix="portfolio-app-result")
    return result


def _compile(context, out: Path) -> tuple[Path, dict[str, dict[str, object]]]:
    scenario_dir = _scenario_directory(context)
    custom = _custom_book(context)
    inherited = None if custom else _payoff_parent(context, scenario_dir)
    if inherited is not None:
        compiled = inherited
    elif custom is not None:
        custom = _objective_book(context, custom)
        result = compile_book(
            context.root, scenario_dir, custom, constraints=custom.get("constraints")
        )
        result = _with_zero_cost_sensitivity(
            result, _zero_cost_sensitivity(context, scenario_dir, custom)
        )
        compiled = {str(custom["book_id"]): result}
    else:
        sources = sorted((context.root / "config" / "books").glob("*.json"))
        books = [json.loads(source.read_text()) for source in sources]
        if context.request.get("objective") in (None, "es"):
            compiled = compile_sample_books(context.root, scenario_dir, out / "books")
        else:
            compiled = {
                book["book_id"]: compile_book(
                    context.root, scenario_dir, _objective_book(context, book)
                )
                for book in books
            }
        for book in books:
            book = _objective_book(context, book)
            compiled[book["book_id"]] = _with_zero_cost_sensitivity(
                compiled[book["book_id"]],
                _zero_cost_sensitivity(context, scenario_dir, book),
            )
    scenario_manifest = json.loads((scenario_dir / "manifest.json").read_text())
    summary = {
        "schema_version": "2.0",
        "analysis_id": context.analysis_id,
        "scenario_artifact": str(scenario_dir),
        "scenario_manifest_id": scenario_manifest.get("artifact_id")
        or content_id(scenario_manifest, prefix="r2j-production"),
        "input_artifacts": context.input_artifacts,
        "book_path": context.request.get("book_path"),
        "books": {book_id: result["result_id"] for book_id, result in compiled.items()},
    }
    return _write(out, "portfolio_manifest.json", summary), compiled


def handle_payoffs(context, out: Path):
    """Compile the three declared books against supplied paths and retain their identities."""
    _, compiled = _compile(context, out)
    for book_id, result in compiled.items():
        _write(out, f"{book_id}.json", result)
    # The executor recursively hashes every written output when this returns None.
    return None


def handle_portfolios(stage: str, context, out: Path):
    """Evaluate/optimize the same frozen book artifacts; no scenario generation occurs here."""
    if stage not in {"portfolios.evaluate", "portfolios.optimize"}:
        raise ValueError(f"unsupported portfolio stage: {stage}")
    _, compiled = _compile(context, out)
    for book_id, result in compiled.items():
        result = dict(result)
        result["stage"] = stage
        result["object_id"] = content_id(
            {
                "analysis_id": context.analysis_id,
                "stage": stage,
                "book_result_id": result["result_id"],
            },
            prefix="portfolio-stage",
        )
        _write(out, f"{book_id}.json", result)
    # Retain nested book/memo exports through the executor's recursive output path.
    return None
