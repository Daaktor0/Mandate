from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import pytest
from mandate_schemas import LightTaskMessage
from mandate_schemas.generated import (
    ClarificationSetQuestionsItemCode,
    LightTaskMessageTaskType,
)
from mandate_worker.preliminary_research import (
    ClarificationPlanner,
    PostgresPreliminaryResearchRepository,
    PreliminaryMaterialSignal,
    PreliminaryResearchError,
    PreliminaryResearchRequest,
    PreliminaryResearchResult,
    PreliminaryResearchRunner,
    PreliminaryResearchTaskHandler,
)
from mandate_worker.providers.page_fetcher import (
    PageDocument,
    PageFetchRequest,
    PageFetchResponse,
    PageRobotsStatus,
)
from mandate_worker.providers.search import SearchRequest, SearchResponse, SearchResult

REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")
ENTITY_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_ID = UUID("33333333-3333-4333-8333-333333333333")
TASK_ID = UUID("44444444-4444-4444-8444-444444444444")
NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def request(
    *signals: PreliminaryMaterialSignal,
) -> PreliminaryResearchRequest:
    return PreliminaryResearchRequest(
        id=REQUEST_ID,
        user_id=USER_ID,
        state="preliminary_research",
        entity_id=ENTITY_ID,
        legal_name="Mandate Demo Company",
        jurisdiction="IN",
        material_signals=signals,
    )


def light_task() -> LightTaskMessage:
    return LightTaskMessage(
        schemaVersion=1,
        taskId=TASK_ID,
        taskType=LightTaskMessageTaskType.PRELIMINARY_RESEARCH,
        reportRequestId=REQUEST_ID,
        userId=USER_ID,
        attempt=1,
        traceId="trace-prelim-01",
    )


class StubSearch:
    async def search(self, search_request: object) -> SearchResponse:
        assert isinstance(search_request, SearchRequest)
        return SearchResponse(
            request=search_request,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            results=(
                SearchResult(
                    title="Synthetic company page",
                    url="https://research.example/source",
                    source_id="source-1",
                ),
            ),
        )


class StubFetcher:
    async def fetch(self, fetch_request: PageFetchRequest) -> PageFetchResponse:
        request_url = fetch_request.url
        return PageFetchResponse(
            request=fetch_request,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            document=PageDocument(
                requested_url=request_url,
                final_url=request_url,
                status_code=200,
                content_type="text/html",
                title="Synthetic company page",
                text="Public synthetic company information.",
                content_sha256="a" * 64,
                robots_status=PageRobotsStatus.FIXTURE,
                prompt_injection_suspected=False,
            ),
        )


def test_RESEARCH_04_planner_always_emits_mandatory_role_question() -> None:
    result = ClarificationPlanner().plan(request(), ())

    assert len(result.questions) == 1
    question = result.questions[0]
    assert question.code is ClarificationSetQuestionsItemCode.CLIENT_ROLE
    assert question.mandatory is True
    assert question.reason
    assert question.confidentiality_safe is True
    assert result.sparse_data is True


@pytest.mark.parametrize(
    ("signal", "code"),
    (
        (
            PreliminaryMaterialSignal.TRANSACTION_OVERLAY,
            ClarificationSetQuestionsItemCode.TRANSACTION_CATEGORY,
        ),
        (
            PreliminaryMaterialSignal.CROSS_BORDER,
            ClarificationSetQuestionsItemCode.CROSS_BORDER,
        ),
        (
            PreliminaryMaterialSignal.KNOWN_PUBLIC_ISSUE,
            ClarificationSetQuestionsItemCode.KNOWN_PUBLIC_ISSUE,
        ),
    ),
)
def test_RESEARCH_02_06_optional_questions_follow_material_signals(
    signal: PreliminaryMaterialSignal,
    code: ClarificationSetQuestionsItemCode,
) -> None:
    result = ClarificationPlanner().plan(request(signal), ())

    assert [item.code for item in result.questions] == [
        ClarificationSetQuestionsItemCode.CLIENT_ROLE,
        code,
    ]
    assert all(
        item.mandatory is (item.code is ClarificationSetQuestionsItemCode.CLIENT_ROLE)
        for item in result.questions
    )


def test_RESEARCH_03_planner_rejects_unsafe_question_policy() -> None:
    planner = ClarificationPlanner()
    unsafe = planner.plan(request(), ())
    unsafe_question = unsafe.questions[0].model_copy(
        update={"prompt": "Please provide confidential terms and passwords."}
    )
    unsafe_set = unsafe.model_copy(update={"questions": [unsafe_question]})

    from mandate_worker import preliminary_research

    with pytest.raises(PreliminaryResearchError, match="sensitive_request"):
        preliminary_research._assert_question_safety(unsafe_set)


@pytest.mark.asyncio
async def test_RESEARCH_01_preliminary_runner_admits_bounded_evidence() -> None:
    result = await PreliminaryResearchRunner(
        search=StubSearch(),
        page_fetcher=StubFetcher(),
        now=NOW,
    ).run(request())

    assert len(result.evidence) == 1
    assert result.evidence[0].entity_id == ENTITY_ID
    assert result.evidence[0].source_tier.value == 3
    assert result.clarification_set.evidence_ids == [result.evidence[0].evidence_id]
    assert result.evidence[0].excerpt == "Public synthetic company information."


@pytest.mark.asyncio
async def test_RESEARCH_01_preliminary_runner_keeps_sparse_result_reviewable() -> None:
    class EmptySearch:
        async def search(self, search_request: object) -> SearchResponse:
            assert isinstance(search_request, SearchRequest)
            return SearchResponse(
                request=search_request,
                provider="fixture",
                fixture=True,
                provider_calls=0,
                results=(),
            )

    result = await PreliminaryResearchRunner(
        search=EmptySearch(),
        page_fetcher=StubFetcher(),
        now=NOW,
    ).run(request())

    assert result.evidence == ()
    assert result.clarification_set.sparse_data is True
    assert result.clarification_set.questions[0].mandatory is True


@dataclass
class RecordingRepository:
    request_value: PreliminaryResearchRequest | None
    loaded: list[tuple[UUID, UUID]] = field(default_factory=list)
    completed: list[PreliminaryResearchResult] = field(default_factory=list)
    failures: list[tuple[UUID, UUID, str]] = field(default_factory=list)

    async def load_request(
        self, report_request_id: UUID, user_id: UUID
    ) -> PreliminaryResearchRequest | None:
        self.loaded.append((report_request_id, user_id))
        return self.request_value

    async def complete(
        self,
        task_id: UUID,
        request_value: PreliminaryResearchRequest,
        result: PreliminaryResearchResult,
    ) -> str:
        assert task_id == TASK_ID
        assert request_value.id == REQUEST_ID
        self.completed.append(result)
        return "awaiting_clarification"

    async def fail(self, task_id: UUID, report_request_id: UUID, error_code: str) -> str:
        self.failures.append((task_id, report_request_id, error_code))
        return "failed_no_charge"


@pytest.mark.asyncio
async def test_RESEARCH_01_light_task_persists_questions_after_confirmation() -> None:
    repository = RecordingRepository(request())
    handler = PreliminaryResearchTaskHandler(
        repository=repository,
        runner=PreliminaryResearchRunner(
            search=StubSearch(),
            page_fetcher=StubFetcher(),
            now=NOW,
        ),
    )

    await handler(light_task())

    assert repository.loaded == [(REQUEST_ID, USER_ID)]
    assert len(repository.completed) == 1
    assert repository.completed[0].clarification_set.questions[0].mandatory is True
    assert repository.failures == []


@pytest.mark.asyncio
async def test_RESEARCH_01_light_task_rejects_wrong_task_type() -> None:
    repository = RecordingRepository(request())
    handler = PreliminaryResearchTaskHandler(
        repository=repository,
        runner=PreliminaryResearchRunner(
            search=StubSearch(),
            page_fetcher=StubFetcher(),
            now=NOW,
        ),
    )
    wrong_task = light_task().model_copy(
        update={"task_type": LightTaskMessageTaskType.RESOLVE_ENTITY}
    )

    with pytest.raises(PreliminaryResearchError, match="unsupported_light_task_type"):
        await handler(wrong_task)
    assert repository.completed == []


@dataclass
class RecordingDatabase:
    rows: list[Mapping[str, object] | None]
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    async def fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object] | None:
        self.calls.append((statement, parameters))
        return self.rows.pop(0)


@pytest.mark.asyncio
async def test_RESEARCH_01_postgres_repository_scopes_confirmed_entity() -> None:
    database = RecordingDatabase(
        [
            {
                "id": REQUEST_ID,
                "user_id": USER_ID,
                "state": "preliminary_research",
                "confirmed_entity_id": ENTITY_ID,
                "related_entity_ids": [],
                "legal_name": "Mandate Demo Company",
                "jurisdiction": "IN",
                "cin": None,
            }
        ]
    )
    loaded = await PostgresPreliminaryResearchRepository(database).load_request(REQUEST_ID, USER_ID)

    assert loaded is not None
    assert loaded.entity_id == ENTITY_ID
    assert loaded.legal_name == "Mandate Demo Company"
    assert database.calls[0][1] == (REQUEST_ID, USER_ID)


@pytest.mark.asyncio
async def test_RESEARCH_01_postgres_repository_completes_atomically() -> None:
    database = RecordingDatabase([{"state": "awaiting_clarification"}])
    repository = PostgresPreliminaryResearchRepository(database)
    planner = ClarificationPlanner()
    result = PreliminaryResearchResult(
        clarificationSet=planner.plan(request(), ()),
        evidence=(),
    )

    assert await repository.complete(TASK_ID, request(), result) == "awaiting_clarification"
    statement, parameters = database.calls[0]
    assert "private.complete_preliminary_research" in statement
    assert parameters[:3] == (TASK_ID, REQUEST_ID, USER_ID)
    assert "confidentialitySafe" in str(parameters[3])
