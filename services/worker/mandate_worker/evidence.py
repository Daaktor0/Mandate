"""Source classification and the explicit untrusted-to-evidence admission gate.

Fetched material is not evidence merely because an adapter returned it.  This
module keeps the source decision deterministic and requires a deliberate
admission call before producing the shared ``Evidence`` object used by later
claim and report stages.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from enum import IntEnum, StrEnum
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from mandate_schemas.generated import (
    Evidence,
    EvidenceEntityIdentifiers,
    EvidenceExtractionMethod,
    EvidenceRetentionClass,
)
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from mandate_worker.entity_resolution.models import DisclosureKind, PageInspection

MAX_EVIDENCE_ID_VALUES = 20
AUTHORITATIVE_HOST_SUFFIXES = (
    ".gov.in",
    ".nic.in",
    ".gov",
)
AUTHORITATIVE_EXACT_HOSTS = frozenset(
    {
        "bseindia.com",
        "cci.gov.in",
        "mca.gov.in",
        "nseindia.com",
        "rbi.org.in",
        "sebi.gov.in",
        "sci.gov.in",
    }
)


class SourceTier(IntEnum):
    """The hierarchy from doc 06; lower numbers are stronger sources."""

    AUTHORITATIVE = 1
    COMPANY_CONTROLLED = 2
    REPUTABLE_INDEPENDENT = 3
    COMMERCIAL_AGGREGATOR = 4
    SOCIAL_USER_GENERATED = 5


class SourceKind(StrEnum):
    """Adapter-supplied classification for sources without an authority domain."""

    AUTHORITATIVE = "authoritative"
    COMPANY_CONTROLLED = "company_controlled"
    REPUTABLE_INDEPENDENT = "reputable_independent"
    COMMERCIAL_AGGREGATOR = "commercial_aggregator"
    SOCIAL_USER_GENERATED = "social_user_generated"


class SourceClassificationError(ValueError):
    """A source cannot be safely assigned a tier from its available metadata."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SourceClassification(BaseModel):
    """Auditable result of source-tier classification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_tier: SourceTier = Field(alias="sourceTier")
    rationale_code: str = Field(
        alias="rationaleCode",
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9_.:-]+$",
    )


class UntrustedEvidenceCandidate(BaseModel):
    """Bounded evidence-shaped data that is not admitted yet."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    job_id: UUID = Field(alias="jobId")
    entity_id: UUID | None = Field(default=None, alias="entityId")
    url: AnyHttpUrl
    canonical_url: AnyHttpUrl = Field(alias="canonicalUrl")
    title: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=300)
    publication_date: date | None = Field(default=None, alias="publicationDate")
    accessed_at: datetime = Field(alias="accessedAt")
    excerpt: str = Field(min_length=1, max_length=4000)
    content_hash: str = Field(alias="contentHash", pattern=r"^[a-f0-9]{64}$")
    entity_identifiers: EvidenceEntityIdentifiers = Field(alias="entityIdentifiers")
    jurisdiction_relevance: str | None = Field(
        default=None,
        alias="jurisdictionRelevance",
        max_length=500,
    )
    company_controlled: bool = Field(alias="companyControlled")
    extraction_method: EvidenceExtractionMethod = Field(alias="extractionMethod")
    prompt_injection_suspected: bool = Field(alias="promptInjectionSuspected")
    licence_notes: str | None = Field(default=None, alias="licenceNotes", max_length=500)
    raw_body_storage_key: str | None = Field(
        default=None,
        alias="rawBodyStorageKey",
        max_length=500,
    )
    retention_class: EvidenceRetentionClass = Field(alias="retentionClass")
    source_kind: SourceKind | None = Field(default=None, alias="sourceKind")
    evidence_admitted: Literal[False] = Field(default=False, alias="evidenceAdmitted")

    @model_validator(mode="after")
    def canonical_url_must_be_stable(self) -> UntrustedEvidenceCandidate:
        if self.canonical_url.scheme != self.url.scheme:
            raise ValueError("canonical URL must preserve the source scheme")
        if self.evidence_admitted:
            raise ValueError("untrusted evidence candidate cannot be admitted")
        if self.accessed_at.tzinfo is None or self.accessed_at.utcoffset() is None:
            raise ValueError("accessed_at must be timezone-aware")
        return self


def classify_source(
    url: str,
    *,
    company_controlled: bool = False,
    source_kind: SourceKind | None = None,
) -> SourceClassification:
    """Assign a doc-06 tier without guessing for an unknown source.

    Government/regulated hosts are recognised only from the narrow allowlist.
    Other tiers require an adapter-provided source kind; an arbitrary URL or
    publisher can never promote itself to authoritative evidence.
    """

    host = (urlsplit(url).hostname or "").rstrip(".").casefold()
    if not host:
        raise SourceClassificationError("source_host_missing")

    if host in AUTHORITATIVE_EXACT_HOSTS or host.endswith(AUTHORITATIVE_HOST_SUFFIXES):
        return SourceClassification(
            sourceTier=SourceTier.AUTHORITATIVE,
            rationaleCode="authoritative_domain_allowlist",
        )

    if company_controlled:
        if source_kind not in {None, SourceKind.COMPANY_CONTROLLED}:
            raise SourceClassificationError("source_company_controlled_kind_conflict")
        return SourceClassification(
            sourceTier=SourceTier.COMPANY_CONTROLLED,
            rationaleCode="company_controlled_source",
        )

    if source_kind is None:
        raise SourceClassificationError("source_tier_unclassified")
    if source_kind is SourceKind.AUTHORITATIVE:
        raise SourceClassificationError("authoritative_domain_unverified")
    if source_kind is SourceKind.COMPANY_CONTROLLED:
        raise SourceClassificationError("company_controlled_source_unverified")

    tier_by_kind = {
        SourceKind.REPUTABLE_INDEPENDENT: SourceTier.REPUTABLE_INDEPENDENT,
        SourceKind.COMMERCIAL_AGGREGATOR: SourceTier.COMMERCIAL_AGGREGATOR,
        SourceKind.SOCIAL_USER_GENERATED: SourceTier.SOCIAL_USER_GENERATED,
    }
    return SourceClassification(
        sourceTier=tier_by_kind[source_kind],
        rationaleCode=f"adapter_declared_{source_kind.value}",
    )


def capture_page_candidate(
    page: PageInspection,
    *,
    job_id: UUID,
    entity_id: UUID | None,
    accessed_at: datetime,
    retention_class: EvidenceRetentionClass = EvidenceRetentionClass.RAW_30D,
    publication_date: date | None = None,
    jurisdiction_relevance: str | None = None,
    licence_notes: str | None = None,
    raw_body_storage_key: str | None = None,
    source_kind: SourceKind | None = None,
) -> UntrustedEvidenceCandidate:
    """Convert a crawler inspection into a bounded, still-untrusted candidate."""

    identifiers = _identifiers_from_disclosures(page.disclosures)
    return UntrustedEvidenceCandidate(
        jobId=job_id,
        entityId=entity_id,
        url=AnyHttpUrl(page.requested_url),
        canonicalUrl=AnyHttpUrl(page.canonical_url),
        title=page.title,
        publisher=page.publisher,
        publicationDate=publication_date,
        accessedAt=accessed_at,
        excerpt=page.excerpt,
        contentHash=page.content_hash,
        entityIdentifiers=identifiers,
        jurisdictionRelevance=jurisdiction_relevance,
        companyControlled=page.company_controlled,
        extractionMethod=EvidenceExtractionMethod.STATIC_HTML,
        promptInjectionSuspected=page.prompt_injection_suspected,
        licenceNotes=licence_notes,
        rawBodyStorageKey=raw_body_storage_key,
        retentionClass=retention_class,
        sourceKind=source_kind,
    )


def admit_evidence(candidate: UntrustedEvidenceCandidate) -> Evidence:
    """Perform the explicit admission step and return the canonical Evidence object."""

    classification = classify_source(
        str(candidate.canonical_url),
        company_controlled=candidate.company_controlled,
        source_kind=candidate.source_kind,
    )
    return Evidence(
        schemaVersion=1,
        evidenceId=_evidence_id(candidate),
        jobId=candidate.job_id,
        entityId=candidate.entity_id,
        url=candidate.url,
        canonicalUrl=candidate.canonical_url,
        title=candidate.title,
        publisher=candidate.publisher,
        sourceTier=classification.source_tier,
        publicationDate=candidate.publication_date,
        accessedAt=candidate.accessed_at,
        excerpt=candidate.excerpt,
        contentHash=candidate.content_hash,
        entityIdentifiers=candidate.entity_identifiers,
        jurisdictionRelevance=candidate.jurisdiction_relevance,
        companyControlled=candidate.company_controlled,
        extractionMethod=candidate.extraction_method,
        promptInjectionSuspected=candidate.prompt_injection_suspected,
        licenceNotes=candidate.licence_notes,
        rawBodyStorageKey=candidate.raw_body_storage_key,
        retentionClass=candidate.retention_class,
    )


def _evidence_id(candidate: UntrustedEvidenceCandidate) -> UUID:
    """Require the caller to provide durable IDs; no content is copied into IDs."""

    # The persistence layer owns generated IDs.  A deterministic UUID is not
    # safe here because two jobs may legitimately capture the same URL/hash.
    # This function is kept separate so the admission boundary is obvious.
    from uuid import uuid4

    return uuid4()


def _identifiers_from_disclosures(
    disclosures: Iterable[object],
) -> EvidenceEntityIdentifiers:
    legal_names: list[str] = []
    cins: list[str] = []
    addresses: list[str] = []
    for disclosure in disclosures:
        kind = getattr(disclosure, "kind", None)
        value = getattr(disclosure, "value", None)
        if not isinstance(value, str) or not value:
            continue
        target = (
            legal_names
            if kind is DisclosureKind.LEGAL_NAME
            else cins
            if kind is DisclosureKind.CIN
            else addresses
            if kind is DisclosureKind.REGISTERED_OFFICE
            else None
        )
        if target is not None and value not in target and len(target) < MAX_EVIDENCE_ID_VALUES:
            target.append(value)
    return EvidenceEntityIdentifiers(
        legalNames=legal_names,
        cins=cins,
        addresses=addresses,
    )
