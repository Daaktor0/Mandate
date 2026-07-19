"""Pre-payment preliminary research and confidentiality-safe clarification planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from mandate_schemas import LightTaskMessage
from mandate_schemas.generated import (
    ClarificationSet,
    ClarificationSetQuestionsItem,
    ClarificationSetQuestionsItemAnswerKind,
    ClarificationSetQuestionsItemCode,
    LightTaskMessageTaskType,
)
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from mandate_worker.entity_resolution.models import PageInspection, PageKind
from mandate_worker.evidence import SourceKind, SourceTier, admit_evidence, capture_page_candidate
from mandate_worker.light_tasks import LightTaskLoop, LightTaskLoopConfig
from mandate_worker.providers.page_fetcher import PageFetcher, PageFetchRequest
from mandate_worker.providers.search import SearchProvider, SearchRequest
from mandate_worker.queue import QueueAdapter

PRELIMINARY_PLANNER_VERSION = "preliminary-clarification-v1"
MAX_PRELIMINARY_RESULTS = 3


class PreliminaryResearchError(RuntimeError):
    """Stable preliminary-task failure without provider or source content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PreliminaryMaterialSignal(StrEnum):
    TRANSACTION_OVERLAY = "transaction_overlay"
    CROSS_BORDER = "cross_border"
    KNOWN_PUBLIC_ISSUE = "known_public_issue"


class PreliminaryResearchRequest(BaseModel):
    """Public, confirmed-entity context loaded by the worker-side task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    user_id: UUID
    state: Literal["preliminary_research"]
    entity_id: UUID
    legal_name: str = Field(min_length=1, max_length=300)
    jurisdiction: str = Field(pattern=r"^[A-Z]{2}$")
    cin: str | None = Field(default=None, max_length=30)
    input_url: AnyHttpUrl | None = None
    related_entity_ids: tuple[UUID, ...] = Field(default=(), max_length=2)
    material_signals: tuple[PreliminaryMaterialSignal, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def related_entities_are_unique(self) -> PreliminaryResearchRequest:
        if len(set(self.related_entity_ids)) != len(self.related_entity_ids):
            raise ValueError("related entity IDs must be unique")
        if self.entity_id in self.related_entity_ids:
            raise ValueError("primary entity cannot be a related entity")
        if len(set(self.material_signals)) != len(self.material_signals):
            raise ValueError("preliminary material signals must be unique")
        return self


class PreliminaryEvidenceReference(BaseModel):
    """Admitted public evidence retained before a paid report job exists."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    evidence_id: UUID = Field(alias="evidenceId")
    entity_id: UUID = Field(alias="entityId")
    url: AnyHttpUrl
    canonical_url: AnyHttpUrl = Field(alias="canonicalUrl")
    title: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=300)
    source_tier: SourceTier = Field(alias="sourceTier")
    accessed_at: datetime = Field(alias="accessedAt")
    excerpt: str = Field(min_length=1, max_length=4000)
    content_hash: str = Field(alias="contentHash", pattern=r"^[a-f0-9]{64}$")
    prompt_injection_suspected: bool = Field(alias="promptInjectionSuspected")

    @model_validator(mode="after")
    def urls_preserve_scheme(self) -> PreliminaryEvidenceReference:
        if self.url.scheme != self.canonical_url.scheme:
            raise ValueError("preliminary evidence URLs must preserve scheme")
        if self.accessed_at.tzinfo is None or self.accessed_at.utcoffset() is None:
            raise ValueError("preliminary evidence access time must be timezone-aware")
        return self


class PreliminaryResearchResult(BaseModel):
    """Bounded pre-payment output persisted by the completion function."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    clarification_set: ClarificationSet = Field(alias="clarificationSet")
    evidence: tuple[PreliminaryEvidenceReference, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def result_is_scoped(self) -> PreliminaryResearchResult:
        evidence_ids = {item.evidence_id for item in self.evidence}
        if any(item not in evidence_ids for item in self.clarification_set.evidence_ids):
            raise ValueError("clarification set references unknown preliminary evidence")
        if any(item.entity_id != self.clarification_set.entity_id for item in self.evidence):
            raise ValueError("preliminary evidence entity scope mismatch")
        return self


class PreliminaryResearchRepository(Protocol):
    async def load_request(
        self,
        report_request_id: UUID,
        user_id: UUID,
    ) -> PreliminaryResearchRequest | None: ...

    async def complete(
        self,
        task_id: UUID,
        request: PreliminaryResearchRequest,
        result: PreliminaryResearchResult,
    ) -> str: ...

    async def fail(self, task_id: UUID, report_request_id: UUID, error_code: str) -> str: ...


class AsyncPreliminaryDatabase(Protocol):
    async def fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class ClarificationPlanner:
    """Deterministic question policy; it never receives matter narrative."""

    version: str = PRELIMINARY_PLANNER_VERSION

    def plan(
        self,
        request: PreliminaryResearchRequest,
        evidence: tuple[PreliminaryEvidenceReference, ...],
    ) -> ClarificationSet:
        questions = [
            ClarificationSetQuestionsItem(
                questionId="client_role",
                code=ClarificationSetQuestionsItemCode.CLIENT_ROLE,
                prompt=(
                    "Which role best describes you for this transaction: company/promoter, "
                    "investor/acquirer, seller/transferor, or other?"
                ),
                reason=(
                    "Your role changes the order and emphasis of research questions "
                    "without changing the underlying public facts."
                ),
                mandatory=True,
                answerKind=ClarificationSetQuestionsItemAnswerKind.SINGLE_SELECT,
                answerOptions=[
                    "company_promoter",
                    "investor_acquirer",
                    "seller_transferor",
                    "other",
                ],
                confidentialitySafe=True,
            )
        ]
        signal_questions = {
            PreliminaryMaterialSignal.TRANSACTION_OVERLAY: ClarificationSetQuestionsItem(
                questionId="transaction_category",
                code=ClarificationSetQuestionsItemCode.TRANSACTION_CATEGORY,
                prompt="Which broad transaction category should the research overlay emphasise?",
                reason=(
                    "A broad category helps prioritise relevant public checks; it does "
                    "not limit the base research."
                ),
                mandatory=False,
                answerKind=ClarificationSetQuestionsItemAnswerKind.OPTIONAL_SELECT,
                answerOptions=["investment", "acquisition", "sale_or_transfer", "other"],
                confidentialitySafe=True,
            ),
            PreliminaryMaterialSignal.CROSS_BORDER: ClarificationSetQuestionsItem(
                questionId="cross_border",
                code=ClarificationSetQuestionsItemCode.CROSS_BORDER,
                prompt=(
                    "Will a foreign investor, counterparty, or ownership connection be "
                    "relevant to this transaction?"
                ),
                reason=(
                    "This determines whether foreign-investment and cross-border "
                    "regulatory touchpoints need extra public-source review."
                ),
                mandatory=False,
                answerKind=ClarificationSetQuestionsItemAnswerKind.OPTIONAL_SELECT,
                answerOptions=["yes", "no", "unknown"],
                confidentialitySafe=True,
            ),
            PreliminaryMaterialSignal.KNOWN_PUBLIC_ISSUE: ClarificationSetQuestionsItem(
                questionId="known_public_issue",
                code=ClarificationSetQuestionsItemCode.KNOWN_PUBLIC_ISSUE,
                prompt=(
                    "Is there a public-record issue you want Mandate to prioritise? "
                    "Do not include confidential matter facts."
                ),
                reason=(
                    "A public-record pointer can focus the risk review while keeping "
                    "confidential matter narrative out of the system."
                ),
                mandatory=False,
                answerKind=ClarificationSetQuestionsItemAnswerKind.SHORT_TEXT,
                answerOptions=[],
                confidentialitySafe=True,
            ),
        }
        for signal in request.material_signals:
            questions.append(signal_questions[signal])
        question_set = ClarificationSet(
            schemaVersion=1,
            reportRequestId=request.id,
            entityId=request.entity_id,
            questions=questions,
            evidenceIds=[item.evidence_id for item in evidence],
            sparseData=len(evidence) < 2,
            plannerVersion=self.version,
        )
        _assert_question_safety(question_set)
        return question_set


@dataclass(frozen=True, slots=True)
class PreliminaryResearchRunner:
    """Capture a small admitted evidence inventory before clarification."""

    search: SearchProvider
    page_fetcher: PageFetcher
    planner: ClarificationPlanner = ClarificationPlanner()
    now: datetime | None = None

    async def run(self, request: PreliminaryResearchRequest) -> PreliminaryResearchResult:
        accessed_at = self.now or datetime.now(UTC)
        try:
            response = await self.search.search(
                SearchRequest(query=f"{request.legal_name} company", limit=MAX_PRELIMINARY_RESULTS)
            )
        except Exception as error:
            if getattr(error, "retryable", False):
                raise
            raise PreliminaryResearchError("preliminary_search_failed") from error

        admitted: list[PreliminaryEvidenceReference] = []
        for result in response.results[:MAX_PRELIMINARY_RESULTS]:
            try:
                fetched = await self.page_fetcher.fetch(PageFetchRequest(url=result.url))
                document = fetched.document
                inspection = PageInspection(
                    requested_url=document.requested_url,
                    canonical_url=document.final_url,
                    page_kind=PageKind.HOME,
                    status_code=document.status_code,
                    title=document.title,
                    publisher=urlsplit(document.final_url).hostname or "unknown",
                    content_type=document.content_type,
                    content_hash=document.content_sha256,
                    excerpt=document.text[:4000],
                    disclosures=(),
                    prompt_injection_suspected=document.prompt_injection_suspected,
                    company_controlled=False,
                    extraction_version=document.extraction_version,
                )
                candidate = capture_page_candidate(
                    inspection,
                    job_id=request.id,
                    entity_id=request.entity_id,
                    accessed_at=accessed_at,
                    source_kind=SourceKind.REPUTABLE_INDEPENDENT,
                )
                admitted_evidence = admit_evidence(candidate)
                admitted.append(
                    PreliminaryEvidenceReference(
                        evidenceId=admitted_evidence.evidence_id,
                        entityId=request.entity_id,
                        url=admitted_evidence.url,
                        canonicalUrl=admitted_evidence.canonical_url,
                        title=admitted_evidence.title,
                        publisher=admitted_evidence.publisher,
                        sourceTier=SourceTier(admitted_evidence.source_tier),
                        accessedAt=admitted_evidence.accessed_at,
                        excerpt=admitted_evidence.excerpt,
                        contentHash=admitted_evidence.content_hash,
                        promptInjectionSuspected=admitted_evidence.prompt_injection_suspected,
                    )
                )
            except Exception:
                continue
        evidence = tuple(admitted)
        return PreliminaryResearchResult(
            clarificationSet=self.planner.plan(request, evidence),
            evidence=evidence,
        )


@dataclass(frozen=True, slots=True)
class PostgresPreliminaryResearchRepository:
    """Least-privilege SQL adapter for the pre-payment light task."""

    database: AsyncPreliminaryDatabase

    async def load_request(
        self,
        report_request_id: UUID,
        user_id: UUID,
    ) -> PreliminaryResearchRequest | None:
        row = await self.database.fetch_one(
            """
            select request.id, request.user_id, request.state,
                   request.confirmed_entity_id, request.related_entity_ids,
                   entity.legal_name, entity.jurisdiction, entity.cin,
                   entity.primary_domain
              from public.report_requests as request
              join public.entities as entity
                on entity.id = request.confirmed_entity_id
             where request.id = $1
               and request.user_id = $2
               and request.state = 'preliminary_research'
            """,
            (report_request_id, user_id),
        )
        if row is None:
            return None
        related = tuple(_uuid_values(row.get("related_entity_ids", ())))
        return PreliminaryResearchRequest(
            id=_uuid_value(row["id"]),
            user_id=_uuid_value(row["user_id"]),
            state="preliminary_research",
            entity_id=_uuid_value(row["confirmed_entity_id"]),
            legal_name=str(row["legal_name"]),
            jurisdiction=str(row["jurisdiction"]),
            cin=None if row.get("cin") is None else str(row["cin"]),
            related_entity_ids=related,
            material_signals=_material_signals(
                jurisdiction=str(row["jurisdiction"]),
                related_entity_ids=related,
            ),
        )

    async def complete(
        self,
        task_id: UUID,
        request: PreliminaryResearchRequest,
        result: PreliminaryResearchResult,
    ) -> str:
        row = await self.database.fetch_one(
            """
            select private.complete_preliminary_research(
                $1::uuid, $2::uuid, $3::uuid, $4::jsonb, $5::jsonb
            ) ->> 'state' as state
            """,
            (
                task_id,
                request.id,
                request.user_id,
                result.clarification_set.model_dump_json(by_alias=True),
                _evidence_json(result),
            ),
        )
        return _state_value(row)

    async def fail(self, task_id: UUID, report_request_id: UUID, error_code: str) -> str:
        row = await self.database.fetch_one(
            """
            select private.fail_preliminary_research(
                $1::uuid, $2::uuid, $3::text
            ) ->> 'state' as state
            """,
            (task_id, report_request_id, error_code),
        )
        return _state_value(row)


@dataclass(frozen=True, slots=True)
class PreliminaryResearchTaskHandler:
    repository: PreliminaryResearchRepository
    runner: PreliminaryResearchRunner

    async def __call__(self, message: LightTaskMessage) -> None:
        if message.task_type is not LightTaskMessageTaskType.PRELIMINARY_RESEARCH:
            raise PreliminaryResearchError("unsupported_light_task_type")
        request = await self.repository.load_request(message.report_request_id, message.user_id)
        if request is None:
            raise PreliminaryResearchError("preliminary_request_not_found")
        try:
            result = await self.runner.run(request)
        except PreliminaryResearchError as error:
            await self.repository.fail(message.task_id, request.id, error.code)
            return
        await self.repository.complete(message.task_id, request, result)

    async def fail_terminal(self, message: LightTaskMessage, error_code: str) -> None:
        await self.repository.fail(message.task_id, message.report_request_id, error_code)


def build_preliminary_research_task_loop(
    queue: QueueAdapter,
    handler: PreliminaryResearchTaskHandler,
    *,
    config: LightTaskLoopConfig | None = None,
) -> LightTaskLoop:
    return LightTaskLoop(
        queue,
        handler,
        config=config,
        terminal_failure_handler=handler.fail_terminal,
    )


def _assert_question_safety(question_set: ClarificationSet) -> None:
    if not any(
        item.mandatory and item.code is ClarificationSetQuestionsItemCode.CLIENT_ROLE
        for item in question_set.questions
    ):
        raise PreliminaryResearchError("mandatory_client_role_question_missing")
    for item in question_set.questions:
        if not item.confidentiality_safe:
            raise PreliminaryResearchError("clarification_question_not_confidentiality_safe")
        sensitive_terms = (
            "password",
            "secret",
            "api key",
            "letterhead",
            "full matter",
            "confidential terms",
        )
        if any(term in f"{item.prompt} {item.reason}".casefold() for term in sensitive_terms):
            raise PreliminaryResearchError("clarification_question_contains_sensitive_request")


def _uuid_value(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _uuid_values(value: object) -> tuple[UUID, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(_uuid_value(item) for item in value)


def _material_signals(
    *,
    jurisdiction: str,
    related_entity_ids: tuple[UUID, ...],
) -> tuple[PreliminaryMaterialSignal, ...]:
    signals: list[PreliminaryMaterialSignal] = []
    if related_entity_ids:
        signals.append(PreliminaryMaterialSignal.TRANSACTION_OVERLAY)
    if jurisdiction != "IN":
        signals.append(PreliminaryMaterialSignal.CROSS_BORDER)
    return tuple(signals)


def _state_value(row: Mapping[str, object] | None) -> str:
    if row is None or not isinstance(row.get("state"), str):
        raise PreliminaryResearchError("preliminary_state_persistence_failed")
    return str(row["state"])


def _evidence_json(result: PreliminaryResearchResult) -> str:
    return "[" + ",".join(item.model_dump_json(by_alias=True) for item in result.evidence) + "]"


__all__ = [
    "ClarificationPlanner",
    "PostgresPreliminaryResearchRepository",
    "PreliminaryEvidenceReference",
    "PreliminaryMaterialSignal",
    "PreliminaryResearchError",
    "PreliminaryResearchRepository",
    "PreliminaryResearchRequest",
    "PreliminaryResearchResult",
    "PreliminaryResearchRunner",
    "PreliminaryResearchTaskHandler",
    "build_preliminary_research_task_loop",
]
