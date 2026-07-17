from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from mandate_schemas.generated import (
    Claim,
    ClaimClaimType,
    ClaimConfidence,
    ClaimFreshness,
    ClaimVerifierStatus,
    Evidence,
    EvidenceEntityIdentifiers,
    EvidenceExtractionMethod,
    EvidenceRetentionClass,
)
from mandate_worker.verifier import (
    ContradictionCoverageVerifier,
    ContradictionResolution,
    VerificationRequest,
)
from pydantic import AnyHttpUrl

JOB_ID = UUID("a0b2c3d4-e5f6-4789-9012-345678901234")
ENTITY_ID = UUID("b0b2c3d4-e5f6-4789-9012-345678901234")


def _evidence(
    evidence_id: UUID,
    *,
    tier: int = 2,
    published: date | None = date(2026, 6, 1),
    suspicious: bool = False,
    entity_id: UUID | None = ENTITY_ID,
) -> Evidence:
    return Evidence(
        schemaVersion=1,
        evidenceId=evidence_id,
        jobId=JOB_ID,
        entityId=entity_id,
        url=AnyHttpUrl("https://example.com/source"),
        canonicalUrl=AnyHttpUrl("https://example.com/source"),
        title="Public source",
        publisher="Example publisher",
        sourceTier=tier,
        publicationDate=published,
        accessedAt=datetime(2026, 7, 1, tzinfo=UTC),
        excerpt="Bounded public excerpt.",
        contentHash="a" * 64,
        entityIdentifiers=EvidenceEntityIdentifiers(
            legalNames=["Mandate Demo Company"], cins=[], addresses=[]
        ),
        jurisdictionRelevance="India",
        companyControlled=False,
        extractionMethod=EvidenceExtractionMethod.FIXTURE,
        promptInjectionSuspected=suspicious,
        licenceNotes=None,
        rawBodyStorageKey=None,
        retentionClass=EvidenceRetentionClass.WITH_REPORT,
    )


def _claim(
    claim_id: UUID,
    evidence_ids: tuple[UUID, ...],
    *,
    object_value: str = "100 crore",
    period: str | None = "FY2025",
    freshness: ClaimFreshness = ClaimFreshness.CURRENT,
    material: bool = True,
) -> Claim:
    return Claim(
        schemaVersion=1,
        claimId=claim_id,
        jobId=JOB_ID,
        entityId=ENTITY_ID,
        subject="Mandate Demo Company",
        predicate="reported revenue",
        object=object_value,
        displayText=f"Mandate Demo Company reported revenue of {object_value}.",
        claimType=ClaimClaimType.VERIFIED_FACT,
        evidenceIds=list(evidence_ids),
        period=period,
        confidence=ClaimConfidence.HIGH,
        freshness=freshness,
        contradictionGroup=None,
        verifierStatus=ClaimVerifierStatus.PENDING,
        reportSections=["business_footprint"],
        modelPromptVersion="research-v1",
        isMaterial=material,
    )


def _request(
    claims: tuple[Claim, ...],
    evidence: tuple[Evidence, ...],
    *,
    topics: tuple[str, ...] = ("business",),
    coverage: dict[str, tuple[UUID, ...]] | None = None,
) -> VerificationRequest:
    return VerificationRequest(
        jobId=JOB_ID,
        entityId=ENTITY_ID,
        claims=claims,
        evidence=evidence,
        expectedTopics=topics,
        coverageMap=coverage or {"business": tuple(item.evidence_id for item in evidence)},
        asOf=date(2026, 7, 17),
    )


def test_REPORT_06_verifier_approves_supported_claim_and_reports_coverage() -> None:
    evidence_id = uuid4()
    claim = _claim(uuid4(), (evidence_id,))

    result = ContradictionCoverageVerifier().verify(_request((claim,), (_evidence(evidence_id),)))

    assert result.approved_claim_ids == (claim.claim_id,)
    assert result.claim_verifications[0].verifier_status is ClaimVerifierStatus.APPROVED
    assert result.coverage.coverage_percent == 100
    assert result.coverage.missing_topics == ()
    assert result.additional_research_recommended is False


def test_REPORT_06_verifier_prefers_stronger_source_without_averaging() -> None:
    weaker_id = uuid4()
    stronger_id = uuid4()
    first = _claim(uuid4(), (weaker_id,), object_value="90 crore")
    second = _claim(uuid4(), (stronger_id,), object_value="100 crore")

    result = ContradictionCoverageVerifier().verify(
        _request((first, second), (_evidence(weaker_id, tier=3), _evidence(stronger_id, tier=1)))
    )

    assert len(result.contradictions) == 1
    contradiction = result.contradictions[0]
    assert contradiction.resolution is ContradictionResolution.PREFER_STRONGER_SOURCE
    assert contradiction.unresolved is False
    statuses = {item.claim_id: item.verifier_status for item in result.claim_verifications}
    assert statuses[second.claim_id] is ClaimVerifierStatus.APPROVED
    assert statuses[first.claim_id] is ClaimVerifierStatus.REJECTED


def test_REPORT_06_verifier_preserves_tied_conflict_as_unresolved() -> None:
    first_id = uuid4()
    second_id = uuid4()
    first = _claim(uuid4(), (first_id,), object_value="90 crore")
    second = _claim(uuid4(), (second_id,), object_value="100 crore")

    result = ContradictionCoverageVerifier().verify(
        _request((first, second), (_evidence(first_id), _evidence(second_id)))
    )

    contradiction = result.contradictions[0]
    assert contradiction.resolution is ContradictionResolution.DISCLOSE_AS_CONFLICT
    assert contradiction.unresolved is True
    assert result.additional_research_recommended is True
    assert all(
        item.verifier_status is ClaimVerifierStatus.CONFLICTED
        for item in result.claim_verifications
    )


def test_REPORT_06_verifier_rejects_duplicate_stale_and_suspicious_claims() -> None:
    evidence_id = uuid4()
    stale_id = uuid4()
    duplicate = _claim(uuid4(), (evidence_id,))
    duplicate_copy = _claim(uuid4(), (evidence_id,))
    stale = _claim(uuid4(), (stale_id,), freshness=ClaimFreshness.STALE)
    suspicious = _claim(uuid4(), (evidence_id,))

    result = ContradictionCoverageVerifier().verify(
        _request(
            (duplicate, duplicate_copy, stale, suspicious),
            (_evidence(evidence_id, suspicious=True), _evidence(stale_id)),
            topics=("business", "regulatory"),
            coverage={"business": (evidence_id,), "regulatory": ()},
        )
    )

    by_id = {item.claim_id: item for item in result.claim_verifications}
    assert "duplicate_claim" in by_id[duplicate_copy.claim_id].reason_codes
    assert by_id[stale.claim_id].verifier_status is ClaimVerifierStatus.REJECTED
    assert "all_supporting_evidence_prompt_suspected" in by_id[suspicious.claim_id].reason_codes
    assert result.coverage.missing_topics == ("business", "regulatory")
    assert result.coverage.suspicious_evidence_ids == (evidence_id,)


def test_REPORT_06_verifier_normalises_numeric_units_and_rejects_unknown_evidence() -> None:
    known_id = uuid4()
    unknown_id = uuid4()
    first = _claim(uuid4(), (known_id,), object_value="₹10 crore")
    second = _claim(uuid4(), (known_id,), object_value="100000000 INR")
    unsupported = _claim(uuid4(), (unknown_id,))

    result = ContradictionCoverageVerifier().verify(
        _request((first, second, unsupported), (_evidence(known_id),))
    )

    assert len(result.contradictions) == 0
    unsupported_result = next(
        item for item in result.claim_verifications if item.claim_id == unsupported.claim_id
    )
    assert unsupported_result.verifier_status is ClaimVerifierStatus.REJECTED
    assert "evidence_reference_unknown" in unsupported_result.reason_codes


def test_REPORT_06_verification_request_rejects_cross_entity_evidence() -> None:
    with pytest.raises(ValueError, match="claims must belong"):
        cross_entity_claim = _claim(uuid4(), ()).model_copy(update={"entity_id": uuid4()})
        VerificationRequest(
            jobId=JOB_ID,
            entityId=ENTITY_ID,
            claims=(cross_entity_claim,),
            evidence=(),
        )
