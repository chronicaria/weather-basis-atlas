# Synthetic CI fixture

The fixture is generated, never downloaded and never committed as an apparent
weather observation.  Run:

```sh
uv run python -c 'from pathlib import Path; from weather_basis.validation.fixtures import generate_fixture; generate_fixture(Path("/tmp/wba-fixture"))'
```

It writes a deterministic 1951-01 through 1996-12 donor tree with 20 real
county FIPS (including Lancaster, Nebraska; Washington, DC through NCEI code
18511; a legacy Connecticut county; and three station counties), 552
37-column nClimGrid-shaped TAVG files, three GHCN-shaped station CSVs, and
small gazetteer/population/TopoJSON inputs.  The values are synthetic output
of the known seeded mean-plus-AR(2) process described in build-plan Section
12.2; they are not NOAA data or results.
