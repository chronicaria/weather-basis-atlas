"""V2 contract, listing, and market-support registry.

Registry records intentionally distinguish documented product rules from a
historical listing and from a market observation.  The frozen public weather
inputs support physical research only; they do not establish either of the
latter two facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from weather_basis.schemas.contracts import ContractSpec, InstrumentListing, MarketObservation
from weather_basis.schemas.vintages import SourceArtifact, SourceSupport, VintageLock

from .calendar import PAIRS, Pair
from .universe import Station, load_universe
from .windows import ContractWindow, resolve_contract_window

_TOP_LEVEL = {"schema_version", "evidence", "contract", "listing", "market"}
_EVIDENCE = {
    "cme_chapter_403",
    "cme_product_slate",
    "calendar_table",
    "exchange_calendar",
}
_CONTRACT = {
    "currency",
    "tick_usd",
    "lot_size",
    "observation_rule",
    "expiry_rule",
    "settlement_rule",
    "correction_rule",
    "evidence_tier",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _strict_mapping(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    return dict(value)


@dataclass(frozen=True)
class ContractRegistry:
    """Frozen rules plus explicit unavailable listing/market records."""

    schema_version: str
    evidence: dict[str, dict[str, Any]]
    contract: dict[str, Any]
    listing: dict[str, Any]
    market: dict[str, Any]
    stations: tuple[Station, ...]

    def contract_spec(self, station_id: str, pair: Pair) -> ContractSpec:
        station = next((item for item in self.stations if item.ghcnd_id == station_id), None)
        if station is None:
            raise KeyError(f"unknown contract station: {station_id}")
        if pair not in PAIRS:
            raise ValueError(f"{pair.key} is not in the retained monthly contract calendar")
        code = station.hdd_code if pair.index == "HDD" else station.cdd_code
        return ContractSpec(
            schema_version=self.schema_version,
            contract_spec_id=f"v2:cme-temperature:{station.icao}:{pair.index}",
            index_definition_id=f"v2:cme-temperature-index:{station.icao}:{pair.index}",
            station_id=station.ghcnd_id,
            station_name=station.station_name,
            city=station.city,
            index=pair.index,
            product_code=code,
            multiplier_usd=station.multiplier_usd,
            currency=self.contract["currency"],
            tick_usd=self.contract["tick_usd"],
            lot_size=self.contract["lot_size"],
            observation_rule=station.day_rule,
            expiry_rule=self.contract["expiry_rule"],
            settlement_rule=station.settlement_rule,
            correction_rule=self.contract["correction_rule"],
            effective_from=station.listed_from if station.listed_from != "legacy" else None,
            effective_to=None,
            evidence_tier=self.contract["evidence_tier"],
            evidence_ids=("cme_chapter_403", "calendar_table"),
        )

    def contract_window(
        self, pair: Pair, valuation_date: date, *, contract_year: int | None = None
    ) -> ContractWindow:
        return resolve_contract_window(pair, valuation_date, contract_year=contract_year)

    def instrument_listing(
        self, contract_spec: ContractSpec, contract_year: int, contract_window: ContractWindow
    ) -> InstrumentListing:
        """Return an explicit unknown record; no historical symbols are inferred."""

        if contract_window.contract_year != contract_year:
            raise ValueError("contract year must agree with the contract window")
        return InstrumentListing(
            schema_version=self.schema_version,
            instrument_listing_id=f"v2:listing:{contract_spec.contract_spec_id}:{contract_year}",
            contract_spec_id=contract_spec.contract_spec_id,
            contract_year=contract_year,
            contract_window_id=contract_window.contract_window_id,
            symbol=None,
            listing_status="unknown_historical_listing",
            listed_from=None,
            listed_to=None,
            evidence_ids=(),
            unavailable_reason=self.listing["unknown_historical_listing_reason"],
        )

    def market_observation(
        self, listing: InstrumentListing, *, field_type: str
    ) -> MarketObservation:
        """Return an unavailable record rather than an invented zero price."""

        allowed = set(self.market["supported_field_types"])
        if field_type not in allowed:
            raise ValueError(f"unsupported market field type: {field_type}")
        return MarketObservation(
            schema_version=self.schema_version,
            market_observation_id=f"v2:market:{listing.instrument_listing_id}:{field_type}",
            instrument_listing_id=listing.instrument_listing_id,
            observed_at=None,
            available_at=None,
            field_type=field_type,
            value=None,
            currency=None,
            unit=None,
            source_artifact_id=None,
            access_class=self.market["access_class"],
            executable_status="unavailable",
            unavailable_reason=self.market["unavailable_reason"],
        )


def load_contract_registry(root: Path | None = None) -> ContractRegistry:
    """Load the strict V2 registry without downloading or refreshing inputs."""

    repository = _repo_root() if root is None else Path(root)
    path = repository / "config/contracts/v2-temperature.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    top = _strict_mapping(raw, _TOP_LEVEL, str(path))
    if set(top) != _TOP_LEVEL:
        raise ValueError(f"{path} must contain exactly: {', '.join(sorted(_TOP_LEVEL))}")
    evidence_raw = _strict_mapping(top["evidence"], _EVIDENCE, "evidence")
    evidence_fields = {"source", "uri", "retrieved_on", "sha256", "scope", "status"}
    evidence = {
        key: _strict_mapping(value, evidence_fields, key) for key, value in evidence_raw.items()
    }
    if set(evidence) != _EVIDENCE:
        raise ValueError("registry evidence IDs are incomplete")
    if any(set(value) != evidence_fields for value in evidence.values()):
        raise ValueError("registry evidence fields are incomplete")
    contract = _strict_mapping(top["contract"], _CONTRACT, "contract")
    if set(contract) != _CONTRACT:
        raise ValueError("registry contract fields are incomplete")
    listing = _strict_mapping(top["listing"], {"unknown_historical_listing_reason"}, "listing")
    market = _strict_mapping(
        top["market"], {"access_class", "supported_field_types", "unavailable_reason"}, "market"
    )
    if set(listing) != {"unknown_historical_listing_reason"}:
        raise ValueError("registry listing fields are incomplete")
    if set(market) != {"access_class", "supported_field_types", "unavailable_reason"}:
        raise ValueError("registry market fields are incomplete")
    return ContractRegistry(
        schema_version=str(top["schema_version"]),
        evidence=evidence,
        contract=contract,
        listing=listing,
        market=market,
        stations=load_universe(repository / "data/contracts/cme_city_universe.csv"),
    )


def load_frozen_vintage(root: Path | None = None) -> VintageLock:
    """Load the immutable V1 source-support lock without reading raw weather data."""

    repository = _repo_root() if root is None else Path(root)
    path = repository / "config/vintages/v1-frozen.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    allowed = {
        "schema_version",
        "vintage_id",
        "frozen_on",
        "data_vintage_sha256",
        "market_data_status",
        "official_settlement_status",
        "artifacts",
        "support",
    }
    top = _strict_mapping(raw, allowed, str(path))
    if set(top) != allowed:
        raise ValueError("frozen vintage lock has incomplete fields")
    schema_version = str(top["schema_version"])
    artifacts = tuple(
        SourceArtifact.from_dict({"schema_version": schema_version, **item})
        for item in top["artifacts"]
    )
    support = tuple(
        SourceSupport.from_dict({"schema_version": schema_version, **item})
        for item in top["support"]
    )
    return VintageLock(
        schema_version=schema_version,
        vintage_id=str(top["vintage_id"]),
        frozen_on=str(top["frozen_on"]),
        data_vintage_sha256=str(top["data_vintage_sha256"]),
        artifacts=artifacts,
        support=support,
        market_data_status=str(top["market_data_status"]),
        official_settlement_status=str(top["official_settlement_status"]),
    )
