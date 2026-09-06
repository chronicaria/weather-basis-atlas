.PHONY: env test test-data data contracts indices atlas models quotes nebraska site reproduce v2-fixture-plan v2-fixture-run
DATA_DONOR ?= $(HOME)/Desktop/Code/WeatherDerivativePricing
SNAPSHOT ?= data/snapshots/weather-basis-atlas.tar
REPRO_OUT ?= /tmp/weather-basis-atlas-reproduce
env:
	uv sync --frozen
test:
	uv run ruff check .
	uv run pytest
test-data:
	uv run pytest -o addopts="" -m data tests/data
data:
	uv run wba data migrate --donor $(DATA_DONOR)
	uv run wba data verify
	uv run wba data fetch nclimgrid --variable tmax --start 2023-01 --end 2026-06
	uv run wba data fetch nclimgrid --variable tmin --start 2023-01 --end 2026-06
	uv run wba data fetch ghcnd
	uv run wba data fetch homr
	uv run wba data fetch geography
	uv run wba data fetch population
	uv run wba data fetch geocode
	uv run wba data panel --variable tavg
	uv run wba data panel --variable tmax
	uv run wba data panel --variable tmin
	uv run wba data panel --variable stations
	uv run wba data panel --variable mean_blocks
	uv run wba data qc
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
	uv run wba site build
	uv run wba site check

v2-fixture-plan:
	uv run wba v2 plan --stage portfolios.optimize --spec config/research/v2.yaml --vintage config/vintages/v1-frozen.yaml --profile fixture --request tests/fixtures/v2/portfolio_request.json --out var/runs/v2-fixture-plan.json

v2-fixture-run: v2-fixture-plan
	uv run wba v2 run --plan var/runs/v2-fixture-plan.json --resume
reproduce:
	uv run wba reproduce --snapshot $(SNAPSHOT) --out $(REPRO_OUT)

gate-%:
	uv run wba gate $*
