from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from mandate_schemas import JobMessage
from mandate_worker.queue import MemoryQueueAdapter, QueueName


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.mark.asyncio
async def test_NFR_03_memory_queue_models_visibility_timeout(
    job_message: JobMessage,
) -> None:
    clock = MutableClock(datetime(2026, 7, 13, tzinfo=UTC))
    queue = MemoryQueueAdapter(clock=clock)
    message_id = await queue.send(QueueName.JOBS, job_message)

    first = await queue.lease(QueueName.JOBS, visibility_timeout_seconds=120)
    assert first is not None
    assert first.message_id == message_id
    assert first.read_count == 1
    assert await queue.lease(QueueName.JOBS, visibility_timeout_seconds=120) is None

    clock.advance(seconds=120)
    second = await queue.lease(QueueName.JOBS, visibility_timeout_seconds=120)
    assert second is not None
    assert second.message_id == message_id
    assert second.read_count == 2


@pytest.mark.asyncio
async def test_NFR_03_memory_queue_archives_successful_delivery(
    job_message: JobMessage,
) -> None:
    queue = MemoryQueueAdapter()
    await queue.send(QueueName.JOBS, job_message)
    leased = await queue.lease(QueueName.JOBS, visibility_timeout_seconds=120)
    assert leased is not None

    await queue.archive(QueueName.JOBS, leased.message_id)

    assert await queue.snapshot(QueueName.JOBS) == ()


@pytest.mark.asyncio
async def test_NFR_03_dead_letter_does_not_copy_untrusted_payload(
    job_message: JobMessage,
) -> None:
    queue = MemoryQueueAdapter()
    await queue.send(QueueName.JOBS, job_message)
    leased = await queue.lease(QueueName.JOBS, visibility_timeout_seconds=120)
    assert leased is not None
    leased.payload["confidentialNarrative"] = "must not be copied"

    await queue.dead_letter(
        QueueName.JOBS,
        QueueName.JOBS_DEAD_LETTER,
        leased,
        error_code="invalid error containing sensitive detail",
    )

    records = await queue.snapshot(QueueName.JOBS_DEAD_LETTER)
    assert len(records) == 1
    assert "confidentialNarrative" not in records[0].payload
    assert "must not be copied" not in repr(records[0].payload)
    assert records[0].payload["errorCode"] == "queue_error"
    assert len(str(records[0].payload["payloadSha256"])) == 64
