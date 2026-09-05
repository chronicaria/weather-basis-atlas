"""Strict frozen-source support and vintage-lock records."""

from __future__ import annotations

from dataclasses import dataclass

from .base import StrictRecord, require


@dataclass(frozen=True, kw_only=True)
class SourceArtifact(StrictRecord):
    artifact_id: str
    provider: str
    dataset: str
    source_uri: str
    retrieved_at: str | None
    published_at: str | None
    available_at: str | None
    sha256: str
    byte_count: int | None
    access_class: str
    source_terms: str
    parser_version: str

    def __post_init__(self) -> None:
        super().__post_init__()
        require(len(self.sha256) == 64, "sha256 must be a 64-character digest")
        require(self.byte_count is None or self.byte_count >= 0, "byte_count must be non-negative")


@dataclass(frozen=True, kw_only=True)
class SourceSupport(StrictRecord):
    support_id: str
    artifact_id: str
    variable: str
    location_type: str
    coverage_start: str
    coverage_end: str
    coherent_through: str | None
    retrieval_vintage_id: str
    qc_rule: str
    imputation_rule: str
    station_metadata_breaks: str
    historical_availability: str
    aggregation_order: str
    supported_for: tuple[str, ...]
    unsupported_reason: str | None

    def __post_init__(self) -> None:
        super().__post_init__()
        require(self.variable in {"TAVG", "TMAX", "TMIN", "TMEAN"}, "unsupported weather variable")
        require(self.location_type in {"county", "station"}, "invalid location_type")
        require(bool(self.supported_for), "source support requires a declared use")


@dataclass(frozen=True, kw_only=True)
class VintageLock(StrictRecord):
    vintage_id: str
    frozen_on: str
    data_vintage_sha256: str
    artifacts: tuple[SourceArtifact, ...]
    support: tuple[SourceSupport, ...]
    market_data_status: str
    official_settlement_status: str

    def __post_init__(self) -> None:
        super().__post_init__()
        require(len(self.data_vintage_sha256) == 64, "data_vintage_sha256 must be a digest")
        artifact_ids = {artifact.artifact_id for artifact in self.artifacts}
        require(len(artifact_ids) == len(self.artifacts), "duplicate source artifact IDs")
        require(
            all(item.artifact_id in artifact_ids for item in self.support),
            "source support refers to an unknown artifact",
        )
