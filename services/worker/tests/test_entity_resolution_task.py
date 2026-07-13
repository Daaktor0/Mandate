from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

import pytest
from mandate_schemas import LightTaskMessage
from mandate_schemas.generated import LightTaskMessageTaskType
from mandate_worker.entity_resolution import (
    CandidateGenerationResult,
    EntityCandidateGenerator,
    EntityResolutionTaskHandler,
    PostgresResolutionRepository,
    ResolutionGuidanceCode,
    ResolutionRequest,
    ResolutionTaskError,
)
from mandate_worker.providers.company_data import (
    CompanyDataOperation,
    CompanyDataResponse,
)

TASK_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUEST_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_ID = UUID("33333333-3333-4333-8333-333333333333")


def light_task() -> LightTaskMessage:
    return LightTaskMessage(
        schemaVersion=1,
        taskId=TASK_ID,
        taskType=LightTaskMessageTaskType.RESOLVE_ENTITY,
        reportRequestId=REQUEST_ID,
        userId=USER_ID,
        attempt=1,
        traceId="trace-resolution-task",
    )


class EmptyCompanyProvider:
    async def search_by_name(self, legal_name: str, *, limit: int = 10) -> CompanyDataResponse:
        return CompanyDataResponse(
            operation=CompanyDataOperation.SEARCH_BY_NAME,
            public_query=legal_name,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            records=(),
        )

    async def lookup_by_cin(self, cin: str) -> CompanyDataResponse:
        return CompanyDataResponse(
            operation=CompanyDataOperation.LOOKUP_BY_CIN,
            public_query=cin,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            records=(),
        )


@dataclass
class RecordingRepository:
    request: ResolutionRequest | None
    loaded: list[tuple[UUID, UUID]] = field(default_factory=list)
    completed: list[CandidateGenerationResult] = field(default_factory=list)
    failures: list[tuple[UUID, UUID, str]] = field(default_factory=list)

    async def load_request(
        self, report_request_id: UUID, user_id: UUID
    ) -> ResolutionRequest | None:
        self.loaded.append((report_request_id, user_id))
        return self.request

    async def complete(
        self,
        task_id: UUID,
        request: ResolutionRequest,
        result: CandidateGenerationResult,
    ) -> str:
        assert task_id == TASK_ID
        self.completed.append(result)
        return "failed_no_charge" if not result.candidates else "awaiting_entity_confirmation"

    async def fail(
        self,
        task_id: UUID,
        report_request_id: UUID,
        error_code: str,
    ) -> str:
        self.failures.append((task_id, report_request_id, error_code))
        return "failed_no_charge"


@pytest.mark.asyncio
async def test_ENTITY_04_resolution_task_persists_no_match_without_charge() -> None:
    repository = RecordingRepository(
        ResolutionRequest(
            id=REQUEST_ID,
            user_id=USER_ID,
            input_kind="legal_name",
            input_legal_name="Unknown Company Private Limited",
            state="resolving_entity",
        )
    )
    handler = EntityResolutionTaskHandler(
        repository=repository,
        generator=EntityCandidateGenerator(EmptyCompanyProvider()),
    )

    await handler(light_task())

    assert repository.loaded == [(REQUEST_ID, USER_ID)]
    assert len(repository.completed) == 1
    result = repository.completed[0]
    assert result.candidates == ()
    assert result.guidance_code is ResolutionGuidanceCode.LEGAL_NAME_OR_CIN_REQUIRED
    assert "entitlement" not in repr(result).casefold()


@pytest.mark.asyncio
async def test_SEC_01_resolution_task_fails_closed_on_identifier_mismatch() -> None:
    repository = RecordingRepository(None)
    handler = EntityResolutionTaskHandler(
        repository=repository,
        generator=EntityCandidateGenerator(EmptyCompanyProvider()),
    )

    with pytest.raises(ResolutionTaskError, match="resolution_request_not_found"):
        await handler(light_task())

    assert repository.completed == []


@dataclass
class RecordingDatabase:
    rows: list[Mapping[str, object] | None]
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    async def fetch_one(
        self, statement: str, parameters: tuple[object, ...]
    ) -> Mapping[str, object] | None:
        self.calls.append((statement, parameters))
        return self.rows.pop(0)


@pytest.mark.asyncio
async def test_ENTITY_02_postgres_repository_uses_atomic_completion_function() -> None:
    database = RecordingDatabase([{"state": "failed_no_charge"}])
    repository = PostgresResolutionRepository(database)
    request = ResolutionRequest(
        id=REQUEST_ID,
        user_id=USER_ID,
        input_kind="legal_name",
        input_legal_name="Unknown Company Private Limited",
        state="resolving_entity",
    )
    result = CandidateGenerationResult(
        candidates=(),
        scoreAudits=(),
        providerQueries=1,
        providerCalls=0,
        needsIdentityInput=True,
        guidanceCode=ResolutionGuidanceCode.LEGAL_NAME_OR_CIN_REQUIRED,
    )

    assert await repository.complete(TASK_ID, request, result) == "failed_no_charge"
    statement, parameters = database.calls[0]
    assert "private.complete_entity_resolution" in statement
    assert json.loads(str(parameters[2])) == []
    assert json.loads(str(parameters[3])) == []


@pytest.mark.asyncio
async def test_NFR_01_postgres_repository_persists_terminal_failure_state() -> None:
    database = RecordingDatabase([{"state": "failed_no_charge"}])
    repository = PostgresResolutionRepository(database)

    assert (
        await repository.fail(
            TASK_ID,
            REQUEST_ID,
            "max_light_task_deliveries_exceeded",
        )
        == "failed_no_charge"
    )
    statement, parameters = database.calls[0]
    assert "private.fail_entity_resolution" in statement
    assert parameters == (
        TASK_ID,
        REQUEST_ID,
        "max_light_task_deliveries_exceeded",
    )


def test_ENTITY_03_light_task_contract_has_no_provider_or_profile_payload_fields() -> None:
    payload = light_task().model_dump(mode="json", by_alias=True)

    assert payload["taskType"] == LightTaskMessageTaskType.RESOLVE_ENTITY.value
    assert set(payload) == {
        "schemaVersion",
        "taskId",
        "taskType",
        "reportRequestId",
        "userId",
        "attempt",
        "traceId",
    }
    assert not ({"email", "fullName", "firm", "billing", "letterhead"} & set(payload))
