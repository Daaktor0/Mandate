"""Deterministic contradiction and evidence-coverage verification for stage 8."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, MutableMapping
from datetime import date
from enum import StrEnum
from uuid import UUID, uuid5

from mandate_schemas.generated import (
    Claim,
    ClaimVerifierStatus,
    Evidence,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

VERIFIER_NAMESPACE = UUID("2d76f1d1-4e28-4c1e-9a93-1c7ef6f53e17")
_SPACE_RE = re.compile(r"\s+")
_NUMBER_WITH_UNIT_RE = re.compile(
    r"^(?:(?:₹|inr|rs\.?)\s*)?([0-9]+(?:\.[0-9]+)?)\s*"
    r"(crore|crores|cr|lakh|lakhs|million|billion|percent|%)?\s*(?:inr)?$",
    re.IGNORECASE,
)


class ContradictionSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContradictionResolution(StrEnum):
    PREFER_STRONGER_SOURCE = "prefer_stronger_source"
    PREFER_LATER = "prefer_later"
    DISCLOSE_AS_CONFLICT = "disclose_as_conflict"
    CONVERT_TO_QUESTION = "convert_to_question"


class VerificationRequest(BaseModel):
    """Identifier-scoped stage input; evidence excerpts are never accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID = Field(alias="jobId")
    entity_id: UUID = Field(alias="entityId")
    claims: tuple[Claim, ...] = Field(max_length=100)
    evidence: tuple[Evidence, ...] = Field(max_length=200)
    expected_topics: tuple[str, ...] = Field(default=(), alias="expectedTopics", max_length=20)
    coverage_map: Mapping[str, tuple[UUID, ...]] = Field(default_factory=dict, alias="coverageMap")
    as_of: date = Field(default_factory=date.today, alias="asOf")

    @model_validator(mode="after")
    def request_is_scoped(self) -> VerificationRequest:
        if any(
            claim.job_id != self.job_id or claim.entity_id != self.entity_id
            for claim in self.claims
        ):
            raise ValueError("verification claims must belong to the request job and entity")
        if any(item.job_id != self.job_id for item in self.evidence):
            raise ValueError("verification evidence must belong to the request job")
        if len({item.evidence_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("verification evidence IDs must be unique")
        if len(set(self.expected_topics)) != len(self.expected_topics):
            raise ValueError("verification topics must be unique")
        return self


class ClaimVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    claim_id: UUID = Field(alias="claimId")
    verifier_status: ClaimVerifierStatus = Field(alias="verifierStatus")
    reason_codes: tuple[str, ...] = Field(default=(), alias="reasonCodes", max_length=10)
    contradiction_group: UUID | None = Field(default=None, alias="contradictionGroup")


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    contradiction_id: UUID = Field(alias="contradictionId")
    claim_ids: tuple[UUID, ...] = Field(alias="claimIds", min_length=2, max_length=10)
    evidence_ids: tuple[UUID, ...] = Field(alias="evidenceIds", max_length=50)
    severity: ContradictionSeverity
    resolution: ContradictionResolution
    unresolved: bool
    reason_code: str = Field(alias="reasonCode", pattern=r"^[a-z0-9_:-]{3,100}$")

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> Contradiction:
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("contradiction claim IDs must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("contradiction evidence IDs must be unique")
        return self


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    expected_topics: tuple[str, ...] = Field(alias="expectedTopics", max_length=20)
    covered_topics: tuple[str, ...] = Field(alias="coveredTopics", max_length=20)
    missing_topics: tuple[str, ...] = Field(alias="missingTopics", max_length=20)
    unsupported_claim_ids: tuple[UUID, ...] = Field(alias="unsupportedClaimIds", max_length=100)
    stale_claim_ids: tuple[UUID, ...] = Field(alias="staleClaimIds", max_length=100)
    suspicious_evidence_ids: tuple[UUID, ...] = Field(alias="suspiciousEvidenceIds", max_length=100)
    coverage_percent: int = Field(alias="coveragePercent", ge=0, le=100)


class VerificationResult(BaseModel):
    """Checkpoint-safe output consumed by later analyst/composer stages."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: int = Field(default=1, alias="schemaVersion", frozen=True)
    stage: str = Field(default="verify_contradictions", frozen=True)
    job_id: UUID = Field(alias="jobId")
    entity_id: UUID = Field(alias="entityId")
    claim_verifications: tuple[ClaimVerification, ...] = Field(
        alias="claimVerifications", max_length=100
    )
    contradictions: tuple[Contradiction, ...] = Field(max_length=50)
    coverage: CoverageReport
    approved_claim_ids: tuple[UUID, ...] = Field(alias="approvedClaimIds", max_length=100)
    gaps: tuple[str, ...] = Field(max_length=20)
    additional_research_recommended: bool = Field(alias="additionalResearchRecommended")


class ContradictionCoverageVerifier:
    """Run stage-8 checks without averaging, hiding, or inventing evidence."""

    def verify(self, request: VerificationRequest) -> VerificationResult:
        evidence_by_id = {item.evidence_id: item for item in request.evidence}
        statuses: dict[UUID, ClaimVerification] = {}
        invalid_claim_ids: set[UUID] = set()
        stale_claim_ids: set[UUID] = set()
        suspicious_evidence_ids = {
            item.evidence_id for item in request.evidence if item.prompt_injection_suspected
        }

        for claim in request.claims:
            reason_codes: list[str] = []
            referenced = [evidence_by_id.get(item) for item in claim.evidence_ids]
            if any(item is None for item in referenced):
                reason_codes.append("evidence_reference_unknown")
            claim_evidence = [item for item in referenced if item is not None]
            if any(item.entity_id not in {None, request.entity_id} for item in claim_evidence):
                reason_codes.append("evidence_entity_mismatch")
            if claim.is_material and not claim.evidence_ids:
                reason_codes.append("material_claim_without_evidence")
            if claim.freshness.value == "stale":
                reason_codes.append("claim_stale")
                stale_claim_ids.add(claim.claim_id)
            if claim_evidence and all(
                item.evidence_id in suspicious_evidence_ids for item in claim_evidence
            ):
                reason_codes.append("all_supporting_evidence_prompt_suspected")
            if (
                claim.is_material
                and claim_evidence
                and all(item.source_tier >= 4 for item in claim_evidence)
            ):
                reason_codes.append("material_claim_source_too_weak")
            if reason_codes:
                invalid_claim_ids.add(claim.claim_id)
                status = (
                    ClaimVerifierStatus.PENDING
                    if reason_codes == ["material_claim_source_too_weak"]
                    else ClaimVerifierStatus.REJECTED
                )
            else:
                status = ClaimVerifierStatus.APPROVED
            statuses[claim.claim_id] = ClaimVerification(
                claimId=claim.claim_id,
                verifierStatus=status,
                reasonCodes=tuple(reason_codes),
            )

        seen_assertions: dict[tuple[str, str, str, str], UUID] = {}
        for claim in request.claims:
            key = (
                _normalise(claim.subject),
                _normalise(claim.predicate),
                _normalise_period(claim.period),
                _normalise_assertion(claim.object),
            )
            previous = seen_assertions.get(key)
            if previous is None:
                seen_assertions[key] = claim.claim_id
                continue
            current = statuses[claim.claim_id]
            invalid_claim_ids.add(claim.claim_id)
            statuses[claim.claim_id] = current.model_copy(
                update={
                    "verifier_status": ClaimVerifierStatus.REJECTED,
                    "reason_codes": (*current.reason_codes, "duplicate_claim"),
                }
            )

        contradictions = self._find_contradictions(request, evidence_by_id, statuses)
        for contradiction in contradictions:
            for claim_id in contradiction.claim_ids:
                current = statuses[claim_id]
                status = current.verifier_status
                reasons = list(current.reason_codes)
                if contradiction.unresolved:
                    status = ClaimVerifierStatus.CONFLICTED
                    reasons.append("unresolved_contradiction")
                elif claim_id not in invalid_claim_ids:
                    reasons.append("resolved_contradiction")
                statuses[claim_id] = current.model_copy(
                    update={
                        "verifier_status": status,
                        "reason_codes": tuple(dict.fromkeys(reasons)),
                        "contradiction_group": contradiction.contradiction_id,
                    }
                )

        covered_topics, missing_topics, unsupported_topic_claims = _coverage(
            request, evidence_by_id, statuses
        )
        unsupported_claim_ids = tuple(sorted(invalid_claim_ids | unsupported_topic_claims, key=str))
        approved_claim_ids = tuple(
            sorted(
                (
                    claim_id
                    for claim_id, status in statuses.items()
                    if status.verifier_status is ClaimVerifierStatus.APPROVED
                ),
                key=str,
            )
        )
        coverage_percent = (
            round(len(covered_topics) * 100 / len(request.expected_topics))
            if request.expected_topics
            else 100
        )
        coverage = CoverageReport(
            expectedTopics=request.expected_topics,
            coveredTopics=covered_topics,
            missingTopics=missing_topics,
            unsupportedClaimIds=unsupported_claim_ids,
            staleClaimIds=tuple(sorted(stale_claim_ids, key=str)),
            suspiciousEvidenceIds=tuple(sorted(suspicious_evidence_ids, key=str)),
            coveragePercent=coverage_percent,
        )
        contradiction_gaps = tuple(_gap_reason(item) for item in contradictions if item.unresolved)
        gaps = tuple(dict.fromkeys((*missing_topics, *contradiction_gaps)))
        return VerificationResult(
            jobId=request.job_id,
            entityId=request.entity_id,
            claimVerifications=tuple(statuses[item.claim_id] for item in request.claims),
            contradictions=tuple(contradictions),
            coverage=coverage,
            approvedClaimIds=approved_claim_ids,
            gaps=gaps[:20],
            additionalResearchRecommended=bool(gaps or unsupported_claim_ids),
        )

    @staticmethod
    def _find_contradictions(
        request: VerificationRequest,
        evidence_by_id: Mapping[UUID, Evidence],
        statuses: MutableMapping[UUID, ClaimVerification],
    ) -> tuple[Contradiction, ...]:
        groups: dict[tuple[str, str, str], list[Claim]] = {}
        for claim in request.claims:
            if statuses[claim.claim_id].verifier_status is ClaimVerifierStatus.REJECTED:
                continue
            key = (
                _normalise(claim.subject),
                _normalise(claim.predicate),
                _normalise_period(claim.period),
            )
            groups.setdefault(key, []).append(claim)

        result: list[Contradiction] = []
        for key, claims in groups.items():
            by_object: dict[str, list[Claim]] = {}
            for claim in claims:
                by_object.setdefault(_normalise_assertion(claim.object), []).append(claim)
            if len(by_object) <= 1:
                continue
            grouped_claims = [claim for items in by_object.values() for claim in items]
            claim_ids = tuple(sorted((claim.claim_id for claim in grouped_claims), key=str))
            evidence_ids = tuple(
                sorted(
                    {evidence_id for claim in grouped_claims for evidence_id in claim.evidence_ids},
                    key=str,
                )
            )
            resolution, winner = _resolution(grouped_claims, evidence_by_id)
            unresolved = resolution in {
                ContradictionResolution.DISCLOSE_AS_CONFLICT,
                ContradictionResolution.CONVERT_TO_QUESTION,
            }
            if winner is not None and not unresolved:
                loser_ids = set(claim_ids) - {winner.claim_id}
                for loser_id in loser_ids:
                    current = statuses[loser_id]
                    statuses[loser_id] = current.model_copy(
                        update={
                            "verifier_status": ClaimVerifierStatus.REJECTED,
                            "reason_codes": (
                                *current.reason_codes,
                                "contradicted_by_preferred_claim",
                            ),
                        }
                    )
            contradiction_id = uuid5(
                VERIFIER_NAMESPACE,
                f"{request.job_id}:{request.entity_id}:{key}:{','.join(map(str, claim_ids))}",
            )
            result.append(
                Contradiction(
                    contradictionId=contradiction_id,
                    claimIds=claim_ids,
                    evidenceIds=evidence_ids,
                    severity=(
                        ContradictionSeverity.HIGH
                        if any(claim.is_material for claim in grouped_claims)
                        else ContradictionSeverity.MEDIUM
                    ),
                    resolution=resolution,
                    unresolved=unresolved,
                    reasonCode="same_fact_different_assertion",
                )
            )
        return tuple(result)


def _resolution(
    claims: list[Claim], evidence_by_id: Mapping[UUID, Evidence]
) -> tuple[ContradictionResolution, Claim | None]:
    ranked: list[tuple[tuple[int, int], Claim]] = []
    for claim in claims:
        sources = [evidence_by_id[item] for item in claim.evidence_ids if item in evidence_by_id]
        strongest = min((item.source_tier for item in sources), default=5)
        latest = max(
            (item.publication_date or item.accessed_at.date() for item in sources),
            default=date.min,
        )
        ranked.append(((strongest, -latest.toordinal()), claim))
    ranked.sort(key=lambda item: item[0])
    if not ranked:
        return ContradictionResolution.CONVERT_TO_QUESTION, None
    best_rank = ranked[0][0]
    tied = [item for item in ranked if item[0] == best_rank]
    if len(tied) > 1:
        return ContradictionResolution.DISCLOSE_AS_CONFLICT, None
    if best_rank[0] < 5:
        return (
            ContradictionResolution.PREFER_STRONGER_SOURCE
            if any(item[0][0] != best_rank[0] for item in ranked[1:])
            else ContradictionResolution.PREFER_LATER,
            ranked[0][1],
        )
    return ContradictionResolution.CONVERT_TO_QUESTION, None


def _coverage(
    request: VerificationRequest,
    evidence_by_id: Mapping[UUID, Evidence],
    statuses: Mapping[UUID, ClaimVerification],
) -> tuple[tuple[str, ...], tuple[str, ...], set[UUID]]:
    covered: list[str] = []
    missing: list[str] = []
    unsupported_claims: set[UUID] = set()
    for topic in request.expected_topics:
        evidence_ids = request.coverage_map.get(topic, ())
        topic_claims = [
            claim for claim in request.claims if set(claim.evidence_ids).intersection(evidence_ids)
        ]
        if not evidence_ids or not any(
            claim.claim_id in statuses
            and statuses[claim.claim_id].verifier_status is ClaimVerifierStatus.APPROVED
            for claim in topic_claims
        ):
            missing.append(topic)
        else:
            covered.append(topic)
        for claim in topic_claims:
            if any(item not in evidence_by_id for item in claim.evidence_ids):
                unsupported_claims.add(claim.claim_id)
    return tuple(covered), tuple(missing), unsupported_claims


def _normalise(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    return _SPACE_RE.sub(" ", text)


def _normalise_period(value: str | None) -> str:
    return _normalise(value or "").replace("/", "-")


def _normalise_assertion(value: str) -> str:
    text = _normalise(value).replace("₹", "inr ")
    match = _NUMBER_WITH_UNIT_RE.fullmatch(text)
    if match is not None:
        amount = float(match.group(1))
        unit = (match.group(2) or "").casefold()
        multiplier = {
            "crore": 10_000_000,
            "crores": 10_000_000,
            "cr": 10_000_000,
            "lakh": 100_000,
            "lakhs": 100_000,
            "million": 1_000_000,
            "billion": 1_000_000_000,
        }.get(unit, 1)
        if unit in {"percent", "%"}:
            return f"percent:{amount:g}"
        return f"number:{amount * multiplier:g}"
    return text.replace("rs. ", "inr ").replace("rs ", "inr ")


def _gap_reason(contradiction: Contradiction) -> str:
    return f"contradiction:{contradiction.contradiction_id}"
