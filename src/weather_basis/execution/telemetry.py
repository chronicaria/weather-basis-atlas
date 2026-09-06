"""Small, dependency-free resource observations for one stage execution."""

from __future__ import annotations

import os
import resource
import sys
import time
from dataclasses import dataclass, field
from typing import Any


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


@dataclass
class Telemetry:
    """Monotonic timing and peak process RSS, serializable into manifests."""

    started_wall: float = field(default_factory=time.monotonic)
    started_cpu: float = field(default_factory=time.process_time)
    peak_rss_bytes: int = field(default_factory=_rss_bytes)
    phases_seconds: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int | float] = field(default_factory=dict)

    def observe(self) -> None:
        self.peak_rss_bytes = max(self.peak_rss_bytes, _rss_bytes())

    def phase(self, name: str):
        telemetry = self

        class _Phase:
            def __enter__(self) -> None:
                self.started = time.monotonic()

            def __exit__(self, *_: object) -> None:
                telemetry.phases_seconds[name] = telemetry.phases_seconds.get(name, 0.0) + (
                    time.monotonic() - self.started
                )
                telemetry.observe()

        return _Phase()

    def increment(self, name: str, value: int | float = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + value

    def record(self) -> dict[str, Any]:
        self.observe()
        return {
            "pid": os.getpid(),
            "wall_seconds": time.monotonic() - self.started_wall,
            "cpu_seconds": time.process_time() - self.started_cpu,
            "peak_rss_bytes": self.peak_rss_bytes,
            "phases_seconds": dict(sorted(self.phases_seconds.items())),
            "counters": dict(sorted(self.counters.items())),
        }
