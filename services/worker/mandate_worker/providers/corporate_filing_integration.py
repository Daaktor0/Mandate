"""Confirmation-gated corporate-filing provider selection and acquisition."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from mandate_worker.fixtures import AdapterCapability, FixtureCatalog
from mandate_worker.runtime import RuntimeAdapterPlan

from .corporate_filings import (
    CorporateFilingAcquisitionMethod,
    CorporateFilingAcquisitionResult,
    CorporateFilingDocumentProvider,
    CorporateFilingReference,
    CorporateFilingRequest,
    CorporateFilingType,
    FixtureCorporateFilingProvider,
    ManualMcaVpdProvider,
    register_untrusted_corporate_filing,
)


class CorporateFilingConfigurationError(RuntimeError):
    """Corporate-filing provider selection or fixture wiring is unsafe."""


class ConfirmedCorporateFilingCommand(BaseModel):
    """Identifier-only acquisition command permitted only after entity confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_request_id: UUID
    confirmed_entity_id: UUID
    report_state: Literal["preliminary_research"] = "preliminary_research"
    request: CorporateFilingRequest


class ConfirmedCorporateFilingResult(BaseModel):
    """Acquisition result tied to the confirmed report request and entity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_request_id: UUID
    confirmed_entity_id: UUID
    acquisition: CorporateFilingAcquisitionResult


async def acquire_confirmed_corporate_filings(
    provider: CorporateFilingDocumentProvider,
    command: ConfirmedCorporateFilingCommand,
) -> ConfirmedCorporateFilingResult:
    """Acquire filings only from a command that proves the confirmation state."""

    acquisition = await provider.acquire(command.request)
    if acquisition.request != command.request:
        raise RuntimeError("corporate_filing_provider_request_mismatch")
    return ConfirmedCorporateFilingResult(
        report_request_id=command.report_request_id,
        confirmed_entity_id=command.confirmed_entity_id,
        acquisition=acquisition,
    )


class _FixtureDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    document_id: str = Field(alias="documentId", min_length=1, max_length=128)
    cin: str
    filing_type: CorporateFilingType = Field(alias="filingType")
    financial_year: str | None = Field(default=None, alias="financialYear")
    filed_on: date | None = Field(default=None, alias="filedOn")
    source_locator: str = Field(alias="sourceLocator", min_length=1, max_length=500)
    media_type: Literal["application/pdf", "application/zip", "application/octet-stream"] = Field(
        alias="mediaType"
    )
    body_utf8: str = Field(alias="bodyUtf8", min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def validate_through_public_reference_contract(self) -> Self:
        register_untrusted_corporate_filing(
            document_id=self.document_id,
            cin=self.cin,
            filing_type=self.filing_type,
            financial_year=self.financial_year,
            filed_on=self.filed_on,
            acquisition_method=CorporateFilingAcquisitionMethod.FIXTURE,
            source_provider="fixture",
            source_locator=self.source_locator,
            media_type=self.media_type,
            body=self.body_utf8.encode("utf-8"),
        )
        return self


class _CorporateFilingsFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: Literal[1] = Field(alias="fixtureVersion")
    acquired_at: datetime = Field(alias="acquiredAt")
    documents: tuple[_FixtureDocument, ...] = Field(min_length=1, max_length=50)

    @field_validator("acquired_at")
    @classmethod
    def acquired_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fixture acquiredAt must be timezone-aware")
        return value

    @model_validator(mode="after")
    def document_ids_must_be_unique(self) -> Self:
        document_ids = [document.document_id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("corporate-filing fixture document ids must be unique")
        return self


def fixture_corporate_filing_provider(
    catalog: FixtureCatalog,
) -> FixtureCorporateFilingProvider:
    """Build deterministic scan-pending filing references from the fixture catalog."""

    try:
        fixture = _CorporateFilingsFixture.model_validate(
            catalog.payload(AdapterCapability.CORPORATE_FILINGS)
        )
        documents_by_cin: dict[str, list[CorporateFilingReference]] = {}
        for item in fixture.documents:
            document = register_untrusted_corporate_filing(
                document_id=item.document_id,
                cin=item.cin,
                filing_type=item.filing_type,
                financial_year=item.financial_year,
                filed_on=item.filed_on,
                acquisition_method=CorporateFilingAcquisitionMethod.FIXTURE,
                source_provider="fixture",
                source_locator=item.source_locator,
                media_type=item.media_type,
                body=item.body_utf8.encode("utf-8"),
                acquired_at=fixture.acquired_at,
            )
            documents_by_cin.setdefault(document.cin, []).append(document)
    except (KeyError, ValidationError, ValueError) as error:
        raise CorporateFilingConfigurationError("corporate_filing_fixture_invalid") from error

    return FixtureCorporateFilingProvider(
        {cin: tuple(documents) for cin, documents in documents_by_cin.items()}
    )


def build_corporate_filing_provider(
    plan: RuntimeAdapterPlan,
) -> CorporateFilingDocumentProvider:
    """Build the selected filing provider without credential-driven fallback."""

    binding = plan.bindings[AdapterCapability.CORPORATE_FILINGS]
    if binding == "fixture":
        if not plan.demo_mode or plan.catalog is None:
            raise CorporateFilingConfigurationError("corporate_filing_fixture_requires_demo_mode")
        return fixture_corporate_filing_provider(plan.catalog)
    if binding == "manual_mca_vpd":
        return ManualMcaVpdProvider()
    if binding == "unconfigured":
        raise CorporateFilingConfigurationError("corporate_filing_provider_unconfigured")
    raise CorporateFilingConfigurationError("corporate_filing_provider_not_allowlisted")
