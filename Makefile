.PHONY: env test test-data data contracts indices atlas models quotes nebraska site reproduce
env:
	uv sync --frozen
test:
	uv run ruff check .
	uv run pytest
test-data:
	uv run pytest -o addopts="" -m data tests/data
contracts:
	uv run wba contracts check
indices:
	uv run wba indices build
atlas:
	uv run wba atlas run
	uv run wba atlas headline
models:
	uv run wba models tournament
quotes:
	uv run wba quotes build
nebraska:
	uv run wba nebraska run
site:
	uv run wba site payloads
	uv run wba site build
	uv run wba site check
reproduce:
	uv run wba reproduce

gate-%:
	uv run wba gate $*
