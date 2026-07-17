from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from mandate_schemas.generated import EvidenceRetentionClass
from mandate_worker.entity_resolution.models import (
    DisclosureKind,
    ExtractionBasis,
    LegalDisclosure,
    PageInspection,
    PageKind,
)
from mandate_worker.evidence import (
    SourceClassificationError,
    SourceKind,
    SourceTier,
    UntrustedEvidenceCandidate,
    admit_evidence,
    capture_page_candidate,
    classify_source,
)
from pydantic import ValidationError

JOB_ID = UUID("00000000-0000-4000-8000-000000000001")
ENTITY_ID = UUID("00000000-0000-4000-8000-000000000002")
ACCESSED_AT = datetime(2026, 7, 17, 12, 30, tzinfo=UTC)


def page(*, company_controlled: bool = True, prompt_injection: bool = False) -> PageInspection:
    body = b"Mandate Demo Company public corporate disclosure"
    return PageInspection(
        requested_url="https://mandate-demo.example/about?utm_source=fixture",
        canonical_url="https://mandate-demo.example/about",
        page_kind=PageKind.CORPORATE_DISCLOSURE,
        status_code=200,
        title="Corporate information",
        publisher="Mandate Demo Company",
        content_type="text/html",
        content_hash=hashlib.sha256(body).hexdigest(),
        excerpt="Mandate Demo Company is incorporated in India.",
        disclosures=(
            LegalDisclosure(
                kind=DisclosureKind.LEGAL_NAME,
                value="Mandate Demo Company Private Limited",
                context="Legal name in corporate disclosure.",
                basis=ExtractionBasis.LABEL,
            ),
            LegalDisclosure(
                kind=DisclosureKind.CIN,
                value="U12345MH2020PLC123456",
                context="CIN in corporate disclosure.",
                basis=ExtractionBasis.REGEX,
            ),
            LegalDisclosure(
                kind=DisclosureKind.REGISTERED_OFFICE,
                value="Mumbai, Maharashtra",
                context="Registered office in corporate disclosure.",
                basis=ExtractionBasis.LABEL,
            ),
        ),
        prompt_injection_suspected=prompt_injection,
        company_controlled=company_controlled,
        extraction_version="legal-page-extractor-v1",
    )


def test_REPORT_06_source_tiers_use_authority_allowlist_and_explicit_fallbacks() -> None:
    assert classify_source("https://mca.gov.in/company").source_tier is SourceTier.AUTHORITATIVE
    assert (
        classify_source("https://mandate-demo.example/about", company_controlled=True).source_tier
        is SourceTier.COMPANY_CONTROLLED
    )
    assert (
        classify_source(
            "https://news.example/story",
            source_kind=SourceKind.REPUTABLE_INDEPENDENT,
        ).source_tier
        is SourceTier.REPUTABLE_INDEPENDENT
    )
    assert (
        classify_source(
            "https://social.example/post",
            source_kind=SourceKind.SOCIAL_USER_GENERATED,
        ).source_tier
        is SourceTier.SOCIAL_USER_GENERATED
    )


def test_REPORT_06_unknown_source_fails_closed_and_cannot_claim_authority() -> None:
    with pytest.raises(SourceClassificationError, match="source_tier_unclassified"):
        classify_source("https://unknown.example/source")

    with pytest.raises(SourceClassificationError, match="authoritative_domain_unverified"):
        classify_source(
            "https://unknown.example/source",
            source_kind=SourceKind.AUTHORITATIVE,
        )

    with pytest.raises(SourceClassificationError, match="company_controlled_source_unverified"):
        classify_source(
            "https://unknown.example/source",
            source_kind=SourceKind.COMPANY_CONTROLLED,
        )


def test_RUN_06_page_candidate_is_untrusted_until_explicit_admission() -> None:
    candidate = capture_page_candidate(
        page(),
        job_id=JOB_ID,
        entity_id=ENTITY_ID,
        accessed_at=ACCESSED_AT,
        retention_class=EvidenceRetentionClass.RAW_30D,
    )

    assert candidate.evidence_admitted is False
    assert candidate.entity_identifiers.legal_names == ["Mandate Demo Company Private Limited"]
    assert candidate.entity_identifiers.cins == ["U12345MH2020PLC123456"]
    assert candidate.entity_identifiers.addresses == ["Mumbai, Maharashtra"]

    evidence = admit_evidence(candidate)

    assert evidence.job_id == JOB_ID
    assert evidence.entity_id == ENTITY_ID
    assert evidence.source_tier == SourceTier.COMPANY_CONTROLLED
    assert str(evidence.canonical_url) == "https://mandate-demo.example/about"
    assert evidence.extraction_method.value == "static_html"
    assert evidence.retention_class is EvidenceRetentionClass.RAW_30D


def test_RUN_06_admission_preserves_prompt_injection_suspicion() -> None:
    candidate = capture_page_candidate(
        page(prompt_injection=True),
        job_id=JOB_ID,
        entity_id=ENTITY_ID,
        accessed_at=ACCESSED_AT,
    )

    assert candidate.prompt_injection_suspected is True
    assert admit_evidence(candidate).prompt_injection_suspected is True


def test_RUN_06_non_company_unknown_page_cannot_be_admitted_without_tier() -> None:
    candidate = capture_page_candidate(
        page(company_controlled=False),
        job_id=JOB_ID,
        entity_id=None,
        accessed_at=ACCESSED_AT,
    )

    with pytest.raises(SourceClassificationError, match="source_tier_unclassified"):
        admit_evidence(candidate)


def test_RUN_06_untrusted_candidate_rejects_admitted_flag_and_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        capture_page_candidate(
            page(),
            job_id=JOB_ID,
            entity_id=None,
            accessed_at=datetime(2026, 7, 17, 12, 30),
        )

    with pytest.raises(ValidationError):
        candidate = capture_page_candidate(
            page(),
            job_id=JOB_ID,
            entity_id=None,
            accessed_at=ACCESSED_AT,
        )
        UntrustedEvidenceCandidate.model_validate(
            candidate.model_dump(by_alias=True) | {"evidenceAdmitted": True}
        )
