from __future__ import annotations

from uuid import UUID

import pytest
from mandate_schemas import JobMessage


@pytest.fixture
def job_message() -> JobMessage:
    return JobMessage(
        schema_version=1,
        job_id=UUID("11111111-1111-4111-8111-111111111111"),
        report_request_id=UUID("22222222-2222-4222-8222-222222222222"),
        user_id=UUID("33333333-3333-4333-8333-333333333333"),
        confirmed_entity_id=UUID("44444444-4444-4444-8444-444444444444"),
        attempt=1,
        trace_id="trace-worker-0001",
        budget_profile="mvp-standard",
    )
