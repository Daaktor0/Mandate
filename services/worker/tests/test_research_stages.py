from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from mandate_schemas.generated import (
    ClaimClaimType,
    ClaimConfidence,
    ClaimFreshness,
)
from mandate_worker.agents.research import (
    AgentFinding,
    ClaimDraft,
    ClaimDraftResponse,
    ResearchContext,
    ResearchPlanSlice,
    ResearchStage,
    ResearchStageError,
    ResearchStageRunner,
    TopicStatus,
)
from mandate_worker.budgets import BudgetLedger, BudgetProfile
from mandate_worker.providers.model import ModelBudget
from mandate_worker.providers.page_fetcher import (
    PageDocument,
    PageFetchResponse,
    PageRobotsStatus,
)
from mandate_worker.providers.search import SearchResponse, SearchResult
from pydantic import ValidationError

JOB_ID = UUID("11111111-1111-4111-8111-111111111111")
ENTITY_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


class StubSearch:
    async def search(self, request):
        return SearchResponse(
            request=request,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            results=(
                SearchResult(
                    title="Synthetic research result",
                    url="https://research.example/source",
                    source_id="source-1",
                    highlights=("Synthetic evidence.",),
                ),
            ),
        )


class StubFetcher:
    async def fetch(self, request):
        return PageFetchResponse(
            request=request,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            document=PageDocument(
                requested_url=request.url,
                final_url=request.url,
                status_code=200,
                content_type="text/html",
                title="Synthetic research page",
                text="The company operates in the synthetic sector.",
                content_sha256="a" * 64,
                robots_status=PageRobotsStatus.FIXTURE,
                prompt_injection_suspected=False,
            ),
        )


class StubGateway:
    def __init__(self, response_factory=None) -> None:
        self.payloads = []
        self.response_factory = response_factory or _response_for_task

    async def complete(self, payload, budget, response_model):
        del budget, response_model
        self.payloads.append(payload)
        return SimpleNamespace(parsed=self.response_factory(payload.task, payload.excerpts))


def _context() -> ResearchContext:
    return ResearchContext(
        job_id=JOB_ID,
        entity_id=ENTITY_ID,
        legal_name="Mandate Demo Company",
        cin=None,
        trace_id="trace-research-01",
    )


def _plan(stage: ResearchStage) -> ResearchPlanSlice:
    return ResearchPlanSlice(
        stage=stage,
        objective_code=stage.value.removeprefix("research_") + "_overview",
        topic_codes=("overview",),
        search_budget=2,
        page_budget=1,
        model_budget=ModelBudget(
            max_output_tokens=1600,
            max_call_cost_inr=Decimal("1"),
            job_cost_remaining_inr=Decimal("5"),
        ),
        dynamic_periods=("current", "FY2025", "FY2024", "FY2023"),
        historical_since="2010",
        prompt_bundle_version="research-v1",
    )


def _response_for_task(task: str, excerpts) -> ClaimDraftResponse:
    evidence_id = UUID(excerpts[0].evidence_id)
    kwargs = {
        "subject": "Mandate Demo Company",
        "predicate": "has_research_observation",
        "object": "Synthetic public research observation",
        "display_text": "Mandate Demo Company has a synthetic public research observation.",
        "claim_type": ClaimClaimType.THIRD_PARTY_REPORT,
        "evidence_ids": (evidence_id,),
        "period": "current",
        "confidence": ClaimConfidence.MEDIUM,
        "freshness": ClaimFreshness.CURRENT,
        "report_sections": ("business_footprint",),
        "is_material": True,
        "rationale": "The observation is supported by an admitted source.",
    }
    if task == ResearchStage.COMPETITORS.value:
        kwargs["basis_of_competition"] = "Same customer problem and product category."
    if task == ResearchStage.REGULATORY.value:
        kwargs["confirmation_question"] = "Which licence route should counsel confirm?"
    if task == ResearchStage.PUBLIC_RISK.value:
        kwargs["proceeding_status"] = "reported"
        kwargs["match_basis"] = ("legal_name",)
    return ClaimDraftResponse(
        claims=(ClaimDraft(**kwargs),),
        topic_status={"overview": TopicStatus.COVERED},
        gaps=(),
        suggested_questions=(),
        coverage_map={"overview": (evidence_id,)},
        additional_research_recommended=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", tuple(ResearchStage))
async def test_RUN_03_all_research_stages_emit_typed_agent_finding(stage: ResearchStage) -> None:
    gateway = StubGateway()
    finding = await ResearchStageRunner(
        search=StubSearch(),
        page_fetcher=StubFetcher(),
        model_gateway=gateway,
        now=NOW,
    ).run(_context(), _plan(stage))

    assert isinstance(finding, AgentFinding)
    assert finding.stage is stage
    assert finding.claims[0].evidence_ids
    assert gateway.payloads[0].task == stage.value
    assert gateway.payloads[0].identifiers == {
        "job_id": str(JOB_ID),
        "entity_id": str(ENTITY_ID),
        "trace_id": "trace-research-01",
    }


@pytest.mark.asyncio
async def test_RUN_04_model_receives_admitted_evidence_only() -> None:
    gateway = StubGateway()
    await ResearchStageRunner(
        search=StubSearch(),
        page_fetcher=StubFetcher(),
        model_gateway=gateway,
        now=NOW,
    ).run(_context(), _plan(ResearchStage.BUSINESS))

    excerpt = gateway.payloads[0].excerpts[0]
    assert excerpt.evidence_id
    assert excerpt.text == "The company operates in the synthetic sector."
    assert all("untrusted" not in item.text.lower() for item in gateway.payloads[0].excerpts)


@pytest.mark.asyncio
async def test_RUN_07_research_runner_consumes_ledger_before_each_external_boundary() -> None:
    gateway = StubGateway()
    ledger = BudgetLedger(BudgetProfile.mvp_standard())
    await ResearchStageRunner(
        search=StubSearch(),
        page_fetcher=StubFetcher(),
        model_gateway=gateway,
        budget_ledger=ledger,
        now=NOW,
    ).run(_context(), _plan(ResearchStage.BUSINESS))

    assert ledger.usage.searches == 1
    assert ledger.usage.pages == 1
    assert ledger.usage.model_calls == 1
    assert ledger.usage.input_tokens == 0
    assert ledger.usage.cost_inr == Decimal(0)


@pytest.mark.asyncio
async def test_REPORT_08_dynamic_claim_outside_three_year_window_fails_closed() -> None:
    def stale_response(_task, excerpts):
        response = _response_for_task(ResearchStage.BUSINESS.value, excerpts)
        return response.model_copy(
            update={"claims": (response.claims[0].model_copy(update={"period": "FY2020"}),)}
        )

    with pytest.raises(ResearchStageError, match="research_dynamic_period_outside_window"):
        await ResearchStageRunner(
            search=StubSearch(),
            page_fetcher=StubFetcher(),
            model_gateway=StubGateway(stale_response),
            now=NOW,
        ).run(_context(), _plan(ResearchStage.BUSINESS))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "field", "code"),
    (
        (ResearchStage.COMPETITORS, "basis_of_competition", "research_competitor_basis_missing"),
        (
            ResearchStage.REGULATORY,
            "confirmation_question",
            "research_regulatory_confirmation_missing",
        ),
        (ResearchStage.PUBLIC_RISK, "match_basis", "research_public_risk_identifier_match_weak"),
    ),
)
async def test_REPORT_06_stage_specific_safeguards_fail_closed(stage, field, code) -> None:
    def unsafe_response(_task, excerpts):
        response = _response_for_task(stage.value, excerpts)
        update = {field: None} if field != "match_basis" else {field: ("headline",)}
        return response.model_copy(
            update={"claims": (response.claims[0].model_copy(update=update),)}
        )

    with pytest.raises(ResearchStageError, match=code):
        await ResearchStageRunner(
            search=StubSearch(),
            page_fetcher=StubFetcher(),
            model_gateway=StubGateway(unsafe_response),
            now=NOW,
        ).run(_context(), _plan(stage))


@pytest.mark.asyncio
async def test_REPORT_08_09_current_claim_requires_period() -> None:
    def missing_period_response(_task, excerpts):
        response = _response_for_task(ResearchStage.BUSINESS.value, excerpts)
        return response.model_copy(
            update={"claims": (response.claims[0].model_copy(update={"period": None}),)}
        )

    with pytest.raises(ResearchStageError, match="research_current_claim_period_missing"):
        await ResearchStageRunner(
            search=StubSearch(),
            page_fetcher=StubFetcher(),
            model_gateway=StubGateway(missing_period_response),
            now=NOW,
        ).run(_context(), _plan(ResearchStage.BUSINESS))


def test_RUN_03_finding_rejects_coverage_ids_not_used_by_claims() -> None:
    with pytest.raises(ValidationError, match="coverage map references unknown evidence"):
        AgentFinding(
            schemaVersion=1,
            stage=ResearchStage.BUSINESS,
            jobId=JOB_ID,
            entityId=ENTITY_ID,
            claims=(),
            findingNotes=(),
            topicStatus={"overview": TopicStatus.GAP},
            gaps=("No evidence",),
            suggestedQuestions=(),
            coverageMap={"overview": (uuid4(),)},
            additionalResearchRecommended=True,
        )
