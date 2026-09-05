from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import StrictRecord, require


@dataclass(frozen=True, kw_only=True)
class ResultEnvelope(StrictRecord):
    release_id: str
    object_id: str
    result_type: str
    analysis_id: str
    source_artifact_ids: tuple[str, ...]
    data_vintage_id: str
    model_spec_ids: tuple[str, ...]
    scenario_set_id: str | None
    valuation_asof: str
    index_definition_id: str
    units: str
    currency: str | None
    payload: dict[str, Any] | None
    status: str
    reason_code: str | None
    evidence_reference: str

    def __post_init__(self):
        super().__post_init__()
        require(self.currency in (None, "USD"), "Unsupported public currency")
        require(bool(self.release_id and self.object_id and self.analysis_id), "Missing identity")
        require(bool(self.source_artifact_ids and self.evidence_reference), "Missing provenance")
        require(self.status in ("available", "unavailable", "partial"), "Invalid result status")
        if self.status != "available":
            require(bool(self.reason_code), "Unavailable/partial result requires reason")
        if self.status == "available":
            require(
                self.payload is not None and self.reason_code is None,
                "Available results require payload and no unavailable reason",
            )
