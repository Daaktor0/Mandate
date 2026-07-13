from __future__ import annotations

from uuid import UUID

import pytest
from mandate_schemas import JobMessage


@pytest.fixture
def job_message() -> JobMessage:
    return JobMessage(
        schemaVersion=1,
        jobId=UUID("11111111-1111-4111-8111-111111111111"),
        reportRequestId=UUID("22222222-2222-4222-8222-222222222222"),
        userId=UUID("33333333-3333-4333-8333-333333333333"),
        confirmedEntityId=UUID("44444444-4444-4444-8444-444444444444"),
        attempt=1,
        traceId="trace-worker-0001",
        budgetProfile="mvp-standard",
    )
