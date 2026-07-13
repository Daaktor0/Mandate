"""Entity-resolution light-task orchestration and persistence boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from mandate_schemas import LightTaskMessage
from mandate_schemas.generated import LightTaskMessageTaskType
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from mandate_worker.light_tasks import LightTaskLoop, LightTaskLoopConfig
from mandate_worker.providers.company_data import CompanyDataProviderError
from mandate_worker.queue import QueueAdapter

from .candidates import (
    CandidateGenerationError,
    CandidateGenerationResult,
    EntityCandidateGenerator,
)
from .crawler import LegalPageCrawler


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    user_id: UUID
    input_kind: Literal["website", "legal_name"]
    input_url: AnyHttpUrl | None = None
    input_legal_name: str | None = Field(default=None, min_length=1, max_length=300)
    input_cin: str | None = None
    state: Literal["resolving_entity"]


class ResolutionTaskError(RuntimeError):
    """Stable resolution failure without request or provider detail."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ResolutionRepository(Protocol):
    async def load_request(
        self,
        report_request_id: UUID,
        user_id: UUID,
    ) -> ResolutionRequest | None: ...

    async def complete(
        self,
        task_id: UUID,
        request: ResolutionRequest,
        result: CandidateGenerationResult,
    ) -> str: ...

    async def fail(
        self,
        task_id: UUID,
        report_request_id: UUID,
        error_code: str,
    ) -> str: ...


class AsyncResolutionDatabase(Protocol):
    async def fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class PostgresResolutionRepository:
    """Least-privilege SQL adapter for request loading and atomic completion."""

    database: AsyncResolutionDatabase

    async def load_request(
        self,
        report_request_id: UUID,
        user_id: UUID,
    ) -> ResolutionRequest | None:
        row = await self.database.fetch_one(
            """
            select id, user_id, input_kind::text, input_url, input_legal_name,
                   input_cin, state::text
              from public.report_requests
             where id = %s and user_id = %s
            """,
            (report_request_id, user_id),
        )
        return None if row is None else ResolutionRequest.model_validate(dict(row))

    async def complete(
        self,
        task_id: UUID,
        request: ResolutionRequest,
        result: CandidateGenerationResult,
    ) -> str:
        candidates = json.dumps(
            [item.model_dump(mode="json", by_alias=True) for item in result.candidates],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        audits = json.dumps(
            [item.model_dump(mode="json", by_alias=True) for item in result.score_audits],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        row = await self.database.fetch_one(
            """
            select private.complete_entity_resolution(%s, %s, %s::jsonb, %s::jsonb)::text
              as state
            """,
            (task_id, request.id, candidates, audits),
        )
        state = None if row is None else row.get("state")
        if state not in {"awaiting_entity_confirmation", "failed_no_charge"}:
            raise ResolutionTaskError("resolution_completion_failed")
        return state

    async def fail(
        self,
        task_id: UUID,
        report_request_id: UUID,
        error_code: str,
    ) -> str:
        row = await self.database.fetch_one(
            """
            select private.fail_entity_resolution(%s, %s, %s)::text as state
            """,
            (task_id, report_request_id, error_code),
        )
        state = None if row is None else row.get("state")
        if state not in {"awaiting_entity_confirmation", "failed_no_charge"}:
            raise ResolutionTaskError("resolution_failure_persistence_failed")
        return state


@dataclass(frozen=True, slots=True)
class EntityResolutionTaskHandler:
    repository: ResolutionRepository
    generator: EntityCandidateGenerator
    crawler: LegalPageCrawler | None = None

    async def __call__(self, message: LightTaskMessage) -> None:
        if message.task_type is not LightTaskMessageTaskType.RESOLVE_ENTITY:
            raise ResolutionTaskError("unsupported_light_task_type")
        request = await self.repository.load_request(
            message.report_request_id,
            message.user_id,
        )
        if request is None:
            raise ResolutionTaskError("resolution_request_not_found")

        inspection = None
        if request.input_kind == "website":
            if self.crawler is None or request.input_url is None:
                raise ResolutionTaskError("resolution_crawler_unconfigured")
            inspection = await self.crawler.inspect(str(request.input_url))

        try:
            result = await self.generator.generate(
                report_request_id=request.id,
                supplied_legal_name=request.input_legal_name,
                supplied_cin=request.input_cin,
                site_inspection=inspection,
            )
        except CompanyDataProviderError as error:
            if error.retryable:
                raise
            await self.repository.fail(message.task_id, request.id, error.code)
            return
        except CandidateGenerationError as error:
            await self.repository.fail(message.task_id, request.id, error.code)
            return
        await self.repository.complete(message.task_id, request, result)

    async def fail_terminal(self, message: LightTaskMessage, error_code: str) -> None:
        """Persist a no-charge terminal state before a poison task is archived."""

        await self.repository.fail(
            message.task_id,
            message.report_request_id,
            error_code,
        )


def build_entity_resolution_task_loop(
    queue: QueueAdapter,
    handler: EntityResolutionTaskHandler,
    *,
    config: LightTaskLoopConfig | None = None,
) -> LightTaskLoop:
    """Wire terminal failure persistence as a mandatory resolution-loop control."""

    return LightTaskLoop(
        queue,
        handler,
        config=config,
        terminal_failure_handler=handler.fail_terminal,
    )
