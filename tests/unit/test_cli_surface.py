"""Build-plan Section 3.4: the published command surface remains parseable."""

from __future__ import annotations

from weather_basis.cli import _SNAPSHOT_REPRODUCE_COMMANDS, build_parser


def test_data_fetch_extend_and_snapshot_reproduction_commands_parse() -> None:
    """Section 3.4: frozen-input acquisition and reproduction are explicit CLI actions."""
    parser = build_parser()
    fetch = parser.parse_args(
        [
            "data",
            "fetch",
            "nclimgrid",
            "--variable",
            "tmax",
            "--start",
            "2023-01",
            "--end",
            "2026-06",
        ]
    )
    assert (fetch.data_command, fetch.fetch_command, fetch.variable) == (
        "fetch",
        "nclimgrid",
        "tmax",
    )
    extend = parser.parse_args(
        ["data", "extend", "--through", "2026-07", "--decision", "docs/decisions/0001.md"]
    )
    assert extend.data_command == "extend"
    snapshot = parser.parse_args(
        ["reproduce", "--snapshot", "/tmp/frozen.tar.gz", "--out", "/tmp/reproduced"]
    )
    assert snapshot.snapshot.name == "frozen.tar.gz"


def test_snapshot_reproduction_rebuilds_all_qc_panels() -> None:
    """The clean replay must rebuild every panel consumed by data QC."""
    panel_variables = {
        command[-1]
        for command in _SNAPSHOT_REPRODUCE_COMMANDS
        if command[:2] == ("data", "panel")
    }
    assert {"tavg", "tmax", "tmin", "stations"} <= panel_variables
