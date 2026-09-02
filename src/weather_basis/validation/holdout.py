"""Tournament holdout guard (plan Section 7.6)."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class HoldoutLock:
    """Reject selection access to locked seasons unless explicitly unlocked."""

    start: int = 2023
    end: int = 2025
    env_var: str = "WBA_UNLOCK_HOLDOUT"

    @property
    def unlocked(self) -> bool:
        return os.environ.get(self.env_var) == "1"

    def check(self, seasons: int | Iterable[int], *, selection: bool = True) -> None:
        if not selection or self.unlocked:
            return
        values = [seasons] if isinstance(seasons, int) else list(seasons)
        locked = [int(s) for s in values if self.start <= int(s) <= self.end]
        if locked:
            raise PermissionError(
                f"holdout seasons {locked} are locked; set {self.env_var}=1 for confirmation only"
            )

    def __call__(self, seasons: int | Iterable[int], *, selection: bool = True) -> None:
        self.check(seasons, selection=selection)
