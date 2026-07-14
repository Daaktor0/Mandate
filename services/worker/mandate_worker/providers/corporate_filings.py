"""Typed acquisition boundary for MCA/ROC source filing documents.

This module deliberately does not automate MCA login, payment, CAPTCHA, or user
credentials. It records either a licensed-provider result or a human procurement
requirement and keeps every acquired binary quarantined until malware scanning and
sandbox parsing have completed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CIN_PATTERN = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
FINANCIAL_YEAR_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
MAX_FILING_TYPES = 12
MAX_FINANCIAL_YEARS = 8
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024


def _normalise_cin(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("CIN must be a string")
    cin = value.strip().upper()
    if CIN_PATTERN.fullmatch(cin) is None:
        raise ValueError("CIN is invalid")
    return cin


class CorporateFilingType(StrEnum):
    AOC_4 = "aoc_4"
    AOC_4_XBRL = "aoc_4_xbrl"
    MGT_7 = "mgt_7"
    MGT_7A = "mgt_7a"
    CHARGE = "charge"
    INCORPORATION = "incorporation"
    DIRECTOR_CHANGE = "director_change"
    AUDITOR = "auditor"
    CAPITAL = "capital"
    OTHER = "other"


class CorporateFilingAcquisitionMethod(StrEnum):
    FIXTURE = "fixture"
    LICENSED_VENDOR = "licensed_vendor"
    MANUAL_MCA_VPD = "manual_mca_vpd"
    CONSENTED_ENTITYLOCKER = "consented_entitylocker"


class CorporateFilingAcquisitionStatus(StrEnum):
    READY = "ready"
    HUMAN_ACTION_REQUIRED = "human_action_required"
    UNAVAILABLE = "unavailable"


class CorporateFilingActionCode(StrEnum):
    MCA_VPD_LOGIN_PAYMENT_REQUIRED = "mca_vpd_login_payment_required"
    LICENSED_PROVIDER_UNCONFIGURED = "licensed_provider_unconfigured"
    TARGET_CONSENT_REQUIRED = "target_consent_required"
    NO_MATCHING_DOCUMENTS = "no_matching_documents"


class CorporateFilingRequest(BaseModel):
    """Public, identifier-only request passed to a filing provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cin: str = Field(pattern=CIN_PATTERN.pattern)
    filing_types: tuple[CorporateFilingType, ...] = Field(
        min_length=1, max_length=MAX_FILING_TYPES
    )
    financial_years: tuple[str, ...] = Field(default=(), max_length=MAX_FINANCIAL_YEARS)
    purpose: Literal["transaction_preparation"] = "transaction_preparation"

    @field_validator("cin", mode="before")
    @classmethod
    def normalise_cin(cls, value: object) -> str:
        return _normalise_cin(value)

    @field_validator("filing_types", mode="after")
    @classmethod
    def filing_types_are_unique(
        cls, values: tuple[CorporateFilingType, ...]
    ) -> tuple[CorporateFilingType, ...]:
        if len(values) != len(set(values)):
            raise ValueError("filing types must be unique")
        return values

    @field_validator("financial_years", mode="before")
    @classmethod
    def normalise_financial_years(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list | tuple):
            raise ValueError("financial years must be a sequence")
        years = tuple(str(item).strip() for item in value)
        if any(FINANCIAL_YEAR_PATTERN.fullmatch(item) is None for item in years):
            raise ValueError("financial year must use YYYY-YY")
        if len(years) != len(set(years)):
            raise ValueError("financial years must be unique")
        return years


class CorporateFilingReference(BaseModel):
    """Metadata for an untrusted acquired binary held in quarantine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    cin: str = Field(pattern=CIN_PATTERN.pattern)
    filing_type: CorporateFilingType
    financial_year: str | None = Field(
        default=None, pattern=FINANCIAL_YEAR_PATTERN.pattern
    )
    filed_on: date | None = None
    acquisition_method: CorporateFilingAcquisitionMethod
    source_provider: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]+$"
    )
    source_locator: str = Field(min_length=1, max_length=500)
    acquired_at: datetime
    media_type: Literal[
        "application/pdf", "application/zip", "application/octet-stream"
    ]
    sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    size_bytes: int = Field(ge=1, le=MAX_DOCUMENT_BYTES)
    quarantine_status: Literal["pending_malware_scan"] = "pending_malware_scan"
    parse_allowed: Literal[False] = False

    @field_validator("cin", mode="before")
    @classmethod
    def normalise_cin(cls, value: object) -> str:
        return _normalise_cin(value)

    @field_validator("source_locator")
    @classmethod
    def source_locator_must_not_contain_credentials(cls, value: str) -> str:
        lowered = value.casefold()
        forbidden = ("password=", "token=", "api_key=", "apikey=", "secret=")
        if any(marker in lowered for marker in forbidden):
            raise ValueError("source locator must not contain credentials")
        return value

    @field_validator("acquired_at")
    @classmethod
    def acquired_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquired_at must be timezone-aware")
        return value


class CorporateFilingAcquisitionResult(BaseModel):
    """Bounded provider result with an explicit human-action state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: CorporateFilingRequest
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]+$")
    fixture: bool
    provider_calls: int = Field(ge=0, le=2)
    status: CorporateFilingAcquisitionStatus
    documents: tuple[CorporateFilingReference, ...] = Field(default=(), max_length=50)
    action_code: CorporateFilingActionCode | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> Self:
        if self.status is CorporateFilingAcquisitionStatus.READY:
            if not self.documents or self.action_code is not None:
                raise ValueError(
                    "ready filing result requires documents and no action code"
                )
        elif self.documents or self.action_code is None:
            raise ValueError(
                "non-ready filing result requires one action code and no documents"
            )
        if any(document.cin != self.request.cin for document in self.documents):
            raise ValueError("filing result contains a document for a different CIN")
        return self


class CorporateFilingDocumentProvider(Protocol):
    async def acquire(
        self, request: CorporateFilingRequest
    ) -> CorporateFilingAcquisitionResult:
        """Acquire source filings or return an explicit safe blocker."""


@dataclass(frozen=True, slots=True)
class ManualMcaVpdProvider:
    """Human-in-the-loop MCA View Public Documents procurement boundary."""

    provider_name: str = "mca_vpd_manual"

    async def acquire(
        self, request: CorporateFilingRequest
    ) -> CorporateFilingAcquisitionResult:
        return CorporateFilingAcquisitionResult(
            request=request,
            provider=self.provider_name,
            fixture=False,
            provider_calls=0,
            status=CorporateFilingAcquisitionStatus.HUMAN_ACTION_REQUIRED,
            action_code=CorporateFilingActionCode.MCA_VPD_LOGIN_PAYMENT_REQUIRED,
        )


@dataclass(frozen=True, slots=True)
class FixtureCorporateFilingProvider:
    """Deterministic source-document metadata for tests and demo mode."""

    documents_by_cin: Mapping[str, tuple[CorporateFilingReference, ...]]
    provider_name: str = "fixture"

    async def acquire(
        self, request: CorporateFilingRequest
    ) -> CorporateFilingAcquisitionResult:
        requested_types = set(request.filing_types)
        requested_years = set(request.financial_years)
        documents = tuple(
            document
            for document in self.documents_by_cin.get(request.cin, ())
            if document.filing_type in requested_types
            and (not requested_years or document.financial_year in requested_years)
        )
        if not documents:
            return CorporateFilingAcquisitionResult(
                request=request,
                provider=self.provider_name,
                fixture=True,
                provider_calls=0,
                status=CorporateFilingAcquisitionStatus.UNAVAILABLE,
                action_code=CorporateFilingActionCode.NO_MATCHING_DOCUMENTS,
            )
        return CorporateFilingAcquisitionResult(
            request=request,
            provider=self.provider_name,
            fixture=True,
            provider_calls=0,
            status=CorporateFilingAcquisitionStatus.READY,
            documents=documents,
        )


def register_untrusted_corporate_filing(
    *,
    document_id: str,
    cin: str,
    filing_type: CorporateFilingType,
    acquisition_method: CorporateFilingAcquisitionMethod,
    source_provider: str,
    source_locator: str,
    media_type: Literal[
        "application/pdf", "application/zip", "application/octet-stream"
    ],
    body: bytes,
    financial_year: str | None = None,
    filed_on: date | None = None,
    acquired_at: datetime | None = None,
) -> CorporateFilingReference:
    """Hash and register a binary as scan-pending; never mark it parseable."""

    if not isinstance(body, bytes) or not body:
        raise ValueError("corporate filing body must be non-empty bytes")
    if len(body) > MAX_DOCUMENT_BYTES:
        raise ValueError("corporate filing exceeds the acquisition size cap")
    return CorporateFilingReference(
        document_id=document_id,
        cin=cin,
        filing_type=filing_type,
        financial_year=financial_year,
        filed_on=filed_on,
        acquisition_method=acquisition_method,
        source_provider=source_provider,
        source_locator=source_locator,
        acquired_at=acquired_at or datetime.now(timezone.utc),
        media_type=media_type,
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
    )
