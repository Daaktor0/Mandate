"""Typed, bounded research stages 2--7.

The runner owns the provider order for one stage: search, fetch, explicit
evidence admission, then structured claim drafting through ModelGateway. Raw
page text never crosses the model boundary and no stage can emit an
evidence-less material claim.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID, uuid4

from mandate_schemas.generated import (
    Claim,
    ClaimClaimType,
    ClaimConfidence,
    ClaimFreshness,
    ClaimVerifierStatus,
    Evidence,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mandate_worker.budgets import BudgetLedger
from mandate_worker.entity_resolution.models import PageInspection, PageKind
from mandate_worker.evidence import SourceKind, admit_evidence, capture_page_candidate
from mandate_worker.providers.model import (
    EvidenceExcerpt,
    ModelBudget,
    ModelGateway,
    ModelTaskPayload,
)
from mandate_worker.providers.page_fetcher import (
    PageFetcher,
    PageFetchRequest,
    PageFetchResponse,
)
from mandate_worker.providers.search import SearchProvider, SearchRequest


class ResearchStage(StrEnum):
    BUSINESS = "research_business"
    INDUSTRY = "research_industry"
    COMPETITORS = "research_competitors"
    CORPORATE = "research_corporate"
    REGULATORY = "research_regulatory"
    PUBLIC_RISK = "research_public_risk"


class TopicStatus(StrEnum):
    COVERED = "covered"
    PARTIAL = "partial"
    GAP = "gap"


class ResearchStageError(RuntimeError):
    """Stable stage failure without exposing source or model content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ResearchPlanSlice(BaseModel):
    """The bounded, non-prose input for one research agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: ResearchStage
    objective_code: str = Field(pattern=r"^[a-z0-9_.:-]{3,100}$")
    topic_codes: tuple[str, ...] = Field(min_length=1, max_length=20)
    search_budget: int = Field(ge=1, le=20)
    page_budget: int = Field(ge=1, le=20)
    model_budget: ModelBudget
    dynamic_periods: tuple[str, ...] = Field(min_length=1, max_length=4)
    historical_since: str | None = Field(default=None, max_length=20)
    prompt_bundle_version: str = Field(pattern=r"^[A-Za-z0-9.-]{1,64}$")


class ResearchContext(BaseModel):
    """Identifier-only context permitted to enter the provider pipeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    entity_id: UUID
    legal_name: str = Field(min_length=1, max_length=300)
    cin: str | None = Field(default=None, max_length=30)
    trace_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    role: Literal["investor", "acquirer", "partner", "generic"] = "generic"


class ClaimDraft(BaseModel):
    """Model output before it is bound to the shared Claim schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=500)
    predicate: str = Field(min_length=1, max_length=200)
    object: str = Field(min_length=1, max_length=2000)
    display_text: str = Field(min_length=1, max_length=3000)
    claim_type: ClaimClaimType
    evidence_ids: tuple[UUID, ...] = Field(max_length=50)
    period: str | None = Field(default=None, max_length=200)
    confidence: ClaimConfidence
    freshness: ClaimFreshness
    report_sections: tuple[str, ...] = Field(max_length=20)
    is_material: bool
    rationale: str = Field(min_length=1, max_length=600)
    basis_of_competition: str | None = Field(default=None, max_length=600)
    proceeding_status: str | None = Field(default=None, max_length=80)
    match_basis: tuple[str, ...] = Field(default=(), max_length=8)
    confirmation_question: str | None = Field(default=None, max_length=600)


class ClaimDraftResponse(BaseModel):
    """Strict structured response expected from every stage model call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claims: tuple[ClaimDraft, ...] = Field(max_length=30)
    topic_status: dict[str, TopicStatus]
    gaps: tuple[str, ...] = Field(max_length=20)
    suggested_questions: tuple[str, ...] = Field(max_length=10)
    coverage_map: dict[str, tuple[UUID, ...]]
    additional_research_recommended: bool


class FindingNote(BaseModel):
    """Bounded stage rationale retained beside, never inside, claim prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: UUID = Field(alias="claimId")
    rationale: str = Field(min_length=1, max_length=600)
    basis_of_competition: str | None = Field(
        default=None, alias="basisOfCompetition", max_length=600
    )
    confirmation_question: str | None = Field(
        default=None, alias="confirmationQuestion", max_length=600
    )
    proceeding_status: str | None = Field(default=None, alias="proceedingStatus", max_length=80)
    match_basis: tuple[str, ...] = Field(default=(), alias="matchBasis", max_length=8)


class AgentFinding(BaseModel):
    """Validated checkpoint output for one of research stages 2--7."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = Field(alias="schemaVersion")
    stage: ResearchStage
    job_id: UUID = Field(alias="jobId")
    entity_id: UUID = Field(alias="entityId")
    claims: tuple[Claim, ...] = Field(max_length=30)
    finding_notes: tuple[FindingNote, ...] = Field(alias="findingNotes", max_length=30)
    topic_status: dict[str, TopicStatus] = Field(alias="topicStatus")
    gaps: tuple[str, ...] = Field(max_length=20)
    suggested_questions: tuple[str, ...] = Field(alias="suggestedQuestions", max_length=10)
    coverage_map: dict[str, tuple[UUID, ...]] = Field(alias="coverageMap")
    additional_research_recommended: bool = Field(alias="additionalResearchRecommended")

    @model_validator(mode="after")
    def finding_is_consistent(self) -> AgentFinding:
        claim_ids = {claim.claim_id for claim in self.claims}
        for topic, evidence_ids in self.coverage_map.items():
            claim_evidence_ids = {item for claim in self.claims for item in claim.evidence_ids}
            if not topic or any(
                evidence_id not in claim_evidence_ids for evidence_id in evidence_ids
            ):
                raise ValueError("coverage map references unknown evidence")
        if any(
            claim.job_id != self.job_id or claim.entity_id != self.entity_id
            for claim in self.claims
        ):
            raise ValueError("finding claims must belong to the finding job and entity")
        if len(claim_ids) != len(self.claims):
            raise ValueError("finding claim IDs must be unique")
        if any(note.claim_id not in claim_ids for note in self.finding_notes):
            raise ValueError("finding note references unknown claim")
        if len({note.claim_id for note in self.finding_notes}) != len(self.finding_notes):
            raise ValueError("finding note IDs must be unique")
        return self


class _ResearchDraftGateway(Protocol):
    async def complete(
        self,
        payload: ModelTaskPayload,
        budget: ModelBudget,
        response_model: type[ClaimDraftResponse],
    ) -> object:
        """ModelGateway-compatible structured completion."""


class ResearchStageRunner:
    """Run one bounded stage through SearchProvider, PageFetcher and Gateway."""

    def __init__(
        self,
        *,
        search: SearchProvider,
        page_fetcher: PageFetcher,
        model_gateway: ModelGateway,
        budget_ledger: BudgetLedger | None = None,
        now: datetime | None = None,
    ) -> None:
        self._search = search
        self._page_fetcher = page_fetcher
        self._model_gateway = model_gateway
        self._budget_ledger = budget_ledger
        self._now = now or datetime.now(UTC)

    async def run(self, context: ResearchContext, plan: ResearchPlanSlice) -> AgentFinding:
        if self._budget_ledger is not None:
            self._budget_ledger.start_stage(plan.stage.value)
            self._budget_ledger.consume_search()
        search_response = await self._search.search(
            SearchRequest(
                query=f"{context.legal_name} {plan.objective_code}",
                limit=plan.search_budget,
            )
        )
        fetched = []
        for result in search_response.results[: plan.page_budget]:
            try:
                if self._budget_ledger is not None:
                    self._budget_ledger.consume_page()
                fetched.append(await self._page_fetcher.fetch(PageFetchRequest(url=result.url)))
            except Exception as error:  # provider failures become a bounded gap
                if not getattr(error, "retryable", False):
                    continue

        evidence = self._admit_pages(context, fetched)
        if not evidence:
            raise ResearchStageError("research_no_admitted_evidence")
        excerpts = tuple(
            EvidenceExcerpt(
                evidence_id=str(item.evidence_id),
                source_url=str(item.canonical_url),
                tier=item.source_tier,
                company_controlled=item.company_controlled,
                text=item.excerpt,
            )
            for item in evidence
            if item.source_tier <= 4
        )
        if not excerpts:
            raise ResearchStageError("research_model_evidence_tier_unsupported")
        payload = ModelTaskPayload(
            task=plan.stage.value,
            prompt_bundle_version=plan.prompt_bundle_version,
            identifiers={
                "job_id": str(context.job_id),
                "entity_id": str(context.entity_id),
                "trace_id": context.trace_id,
            },
            excerpts=excerpts,
            context_role=context.role,
        )
        if self._budget_ledger is not None:
            self._budget_ledger.consume_model_call()
        completion = await self._model_gateway.complete(
            payload,
            plan.model_budget,
            ClaimDraftResponse,
        )
        if self._budget_ledger is not None:
            run = getattr(completion, "run", None)
            self._budget_ledger.consume_tokens(
                int(getattr(run, "input_tokens", 0)), int(getattr(run, "output_tokens", 0))
            )
            self._budget_ledger.consume_cost(Decimal(str(getattr(run, "cost_inr", 0))))
        draft_response = getattr(completion, "parsed", None)
        if not isinstance(draft_response, ClaimDraftResponse):
            raise ResearchStageError("research_model_response_invalid")
        return _build_finding(context, plan, draft_response, evidence)

    def _admit_pages(
        self,
        context: ResearchContext,
        fetched: Sequence[PageFetchResponse],
    ) -> tuple[Evidence, ...]:
        admitted: list[Evidence] = []
        for response in fetched:
            document = response.document
            inspection = PageInspection(
                requested_url=document.requested_url,
                canonical_url=document.final_url,
                page_kind=PageKind.HOME,
                status_code=document.status_code,
                title=document.title,
                publisher=document.final_url.split("/", maxsplit=3)[2],
                content_type=document.content_type,
                content_hash=document.content_sha256,
                excerpt=document.text[:4000],
                disclosures=(),
                prompt_injection_suspected=document.prompt_injection_suspected,
                company_controlled=False,
                extraction_version=document.extraction_version,
            )
            try:
                candidate = capture_page_candidate(
                    inspection,
                    job_id=context.job_id,
                    entity_id=context.entity_id,
                    accessed_at=self._now,
                    source_kind=SourceKind.REPUTABLE_INDEPENDENT,
                )
                admitted.append(admit_evidence(candidate))
            except ValueError:
                continue
        return tuple(admitted)


def _build_finding(
    context: ResearchContext,
    plan: ResearchPlanSlice,
    response: ClaimDraftResponse,
    evidence: tuple[Evidence, ...],
) -> AgentFinding:
    evidence_ids = {item.evidence_id for item in evidence}
    claims: list[Claim] = []
    finding_notes: list[FindingNote] = []
    for draft in response.claims:
        if any(item not in evidence_ids for item in draft.evidence_ids):
            raise ResearchStageError("research_claim_evidence_unknown")
        if draft.is_material and not draft.evidence_ids:
            raise ResearchStageError("research_material_claim_without_evidence")
        _validate_stage_rules(plan.stage, draft)
        claim = Claim(
            schemaVersion=1,
            claimId=uuid4(),
            jobId=context.job_id,
            entityId=context.entity_id,
            subject=draft.subject,
            predicate=draft.predicate,
            object=draft.object,
            displayText=draft.display_text,
            claimType=draft.claim_type,
            evidenceIds=list(draft.evidence_ids),
            period=draft.period,
            confidence=draft.confidence,
            freshness=draft.freshness,
            verifierStatus=ClaimVerifierStatus.PENDING,
            reportSections=list(draft.report_sections),
            modelPromptVersion=plan.prompt_bundle_version,
            isMaterial=draft.is_material,
        )
        claims.append(claim)
        finding_notes.append(
            FindingNote(
                claimId=claim.claim_id,
                rationale=draft.rationale,
                basisOfCompetition=draft.basis_of_competition,
                confirmationQuestion=draft.confirmation_question,
                proceedingStatus=draft.proceeding_status,
                matchBasis=draft.match_basis,
            )
        )
    _validate_freshness(plan, response.claims)
    claim_evidence = {item for claim in claims for item in claim.evidence_ids}
    if any(item not in claim_evidence for ids in response.coverage_map.values() for item in ids):
        raise ResearchStageError("research_coverage_evidence_unknown")
    return AgentFinding(
        schemaVersion=1,
        stage=plan.stage,
        jobId=context.job_id,
        entityId=context.entity_id,
        claims=tuple(claims),
        findingNotes=tuple(finding_notes),
        topicStatus=response.topic_status,
        gaps=response.gaps,
        suggestedQuestions=response.suggested_questions,
        coverageMap=response.coverage_map,
        additionalResearchRecommended=response.additional_research_recommended,
    )


def _validate_stage_rules(stage: ResearchStage, draft: ClaimDraft) -> None:
    if stage is ResearchStage.COMPETITORS and draft.is_material:
        if not draft.rationale or not draft.basis_of_competition:
            raise ResearchStageError("research_competitor_basis_missing")
    if stage is ResearchStage.REGULATORY and draft.is_material:
        if not draft.confirmation_question:
            raise ResearchStageError("research_regulatory_confirmation_missing")
    if stage is ResearchStage.PUBLIC_RISK and draft.is_material:
        if not draft.proceeding_status or not draft.match_basis:
            raise ResearchStageError("research_public_risk_match_basis_missing")
        allowed_match_basis = {
            "legal_name",
            "cin",
            "address",
            "director",
            "official_party_record",
        }
        if not allowed_match_basis.intersection(draft.match_basis):
            raise ResearchStageError("research_public_risk_identifier_match_weak")


def _validate_freshness(plan: ResearchPlanSlice, drafts: tuple[ClaimDraft, ...]) -> None:
    current_periods = set(plan.dynamic_periods)
    for draft in drafts:
        if draft.period is None:
            if draft.is_material and draft.freshness in {
                ClaimFreshness.CURRENT,
                ClaimFreshness.RECENT,
            }:
                raise ResearchStageError("research_current_claim_period_missing")
            continue
        if (
            draft.freshness in {ClaimFreshness.CURRENT, ClaimFreshness.RECENT}
            and draft.period not in current_periods
        ):
            raise ResearchStageError("research_dynamic_period_outside_window")
        if plan.historical_since is not None and draft.period < plan.historical_since:
            raise ResearchStageError("research_historical_period_before_incorporation")


__all__ = [
    "AgentFinding",
    "ClaimDraft",
    "ClaimDraftResponse",
    "FindingNote",
    "ResearchContext",
    "ResearchPlanSlice",
    "ResearchStage",
    "ResearchStageError",
    "ResearchStageRunner",
    "TopicStatus",
]
