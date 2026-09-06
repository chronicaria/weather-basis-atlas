"""Application adapter for the explicitly registered B26 pilot."""

from __future__ import annotations

from pathlib import Path


def handle_next_station(context, out: Path):
    """Run only when the stage planner reaches B26 after its accepted parents."""
    from weather_basis.research.next_station import write_pilot

    return write_pilot(context.root, out)
