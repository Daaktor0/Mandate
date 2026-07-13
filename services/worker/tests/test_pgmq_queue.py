from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from mandate_schemas import JobMessage
from mandate_worker.queue import LeasedMessage, PgmqQueueAdapter, QueueName


class RecordingDatabase:
    def __init__(self, rows: list[Mapping[str, object] | None]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch_one(
        self, statement: str, parameters: tuple[object, ...]
    ) -> Mapping[str, object] | None:
        self.calls.append((statement, parameters))
        return self.rows.pop(0)


@pytest.mark.asyncio
async def test_NFR_03_pgmq_adapter_uses_documented_lease_functions(
    job_message: JobMessage,
) -> None:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    database = RecordingDatabase(
        [
            {"message_id": 41},
            {
                "msg_id": 41,
                "read_ct": 1,
                "enqueued_at": now,
                "vt": now,
                "message": job_message.model_dump(mode="json", by_alias=True),
            },
            {"message_id": 41},
            {"archived": True},
        ]
    )
    queue = PgmqQueueAdapter(database)

    assert await queue.send(QueueName.JOBS, job_message) == 41
    leased = await queue.lease(QueueName.JOBS, visibility_timeout_seconds=120)
    assert leased is not None
    await queue.extend_lease(
        QueueName.JOBS,
        leased.message_id,
        visibility_timeout_seconds=120,
    )
    await queue.archive(QueueName.JOBS, leased.message_id)

    statements = "\n".join(statement for statement, _ in database.calls)
    assert "pgmq.send" in statements
    assert "pgmq.read" in statements
    assert "pgmq.set_vt" in statements
    assert "pgmq.archive" in statements
    send_payload = json.loads(str(database.calls[0][1][1]))
    assert send_payload["traceId"] == job_message.trace_id
    assert "fullName" not in send_payload
    assert "firm" not in send_payload


@pytest.mark.asyncio
async def test_NFR_03_pgmq_dead_letter_is_atomic_and_sanitised() -> None:
    database = RecordingDatabase([{"archived": True}])
    queue = PgmqQueueAdapter(database)
    now = datetime(2026, 7, 13, tzinfo=UTC)
    leased = LeasedMessage(
        message_id=9,
        read_count=4,
        enqueued_at=now,
        visible_at=now,
        payload={"confidentialNarrative": "must not be persisted"},
    )

    await queue.dead_letter(
        QueueName.JOBS,
        QueueName.JOBS_DEAD_LETTER,
        leased,
        error_code="invalid_job_message",
    )

    statement, parameters = database.calls[0]
    assert "with dead_letter" in statement.lower()
    assert "pgmq.send" in statement
    assert "pgmq.archive" in statement
    dlq_payload = json.loads(str(parameters[1]))
    assert "confidentialNarrative" not in dlq_payload
    assert "must not be persisted" not in str(dlq_payload)
    assert dlq_payload["sourceMessageId"] == 9
