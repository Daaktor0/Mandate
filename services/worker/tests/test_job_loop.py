from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from mandate_schemas import JobMessage, LightTaskMessage
from mandate_worker.job_loop import JobLoop, JobLoopConfig
from mandate_worker.queue import LeasedMessage, MemoryQueueAdapter, QueueName


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def exception(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.mark.asyncio
async def test_NFR_04_job_loop_archives_a_successful_typed_job(
    job_message: JobMessage,
) -> None:
    queue = MemoryQueueAdapter()
    logger = RecordingLogger()
    handled: list[JobMessage] = []

    async def handle(message: JobMessage) -> None:
        handled.append(message)

    await queue.send(QueueName.JOBS, job_message)
    loop = JobLoop(queue, handle, logger=logger)

    assert await loop.run_once() is True
    assert handled == [job_message]
    assert await queue.snapshot(QueueName.JOBS) == ()
    assert [event for event, _ in logger.events] == ["job_started", "job_archived"]


@pytest.mark.asyncio
async def test_NFR_01_job_loop_leaves_failure_for_visibility_retry(
    job_message: JobMessage,
) -> None:
    queue = MemoryQueueAdapter()
    logger = RecordingLogger()

    async def fail(_message: JobMessage) -> None:
        raise RuntimeError("fixture failure")

    await queue.send(QueueName.JOBS, job_message)
    loop = JobLoop(queue, fail, logger=logger)

    assert await loop.run_once() is True
    assert len(await queue.snapshot(QueueName.JOBS)) == 1
    failure_event = logger.events[-1]
    assert failure_event[0] == "job_attempt_failed"
    assert failure_event[1]["failure_state"] == "retry_wait"


@pytest.mark.asyncio
async def test_NFR_01_job_loop_allows_three_redeliveries_then_dead_letters(
    job_message: JobMessage,
) -> None:
    clock = MutableClock(datetime(2026, 7, 13, tzinfo=UTC))
    queue = MemoryQueueAdapter(clock=clock)
    handled = 0

    async def fail(_message: JobMessage) -> None:
        nonlocal handled
        handled += 1
        raise RuntimeError("fixture failure")

    await queue.send(QueueName.JOBS, job_message)
    loop = JobLoop(
        queue,
        fail,
        config=JobLoopConfig(visibility_timeout_seconds=1),
        logger=RecordingLogger(),
    )

    for _ in range(4):
        assert await loop.run_once() is True
        clock.advance(seconds=1)
    assert await loop.run_once() is True

    assert handled == 4
    assert await queue.snapshot(QueueName.JOBS) == ()
    dead_letters = await queue.snapshot(QueueName.JOBS_DEAD_LETTER)
    assert len(dead_letters) == 1
    assert dead_letters[0].payload["errorCode"] == "max_deliveries_exceeded"


@pytest.mark.asyncio
async def test_NFR_03_job_loop_rejects_invalid_message_without_handling(
    job_message: JobMessage,
) -> None:
    queue = MemoryQueueAdapter()
    logger = RecordingLogger()
    handled = False

    async def handle(_message: JobMessage) -> None:
        nonlocal handled
        handled = True

    await queue.send(QueueName.JOBS, job_message)
    leased = await queue.lease(QueueName.JOBS, visibility_timeout_seconds=1)
    assert leased is not None
    invalid_message = leased
    invalid_message.payload["schemaVersion"] = 99

    # Reinsert the deliberately invalid fixture through the test-only snapshot path.
    # The adapter returns defensive payload copies, so use a tiny transport facade.
    class InvalidTransport:
        async def send(
            self,
            queue_name: QueueName,
            message: JobMessage | LightTaskMessage,
            *,
            delay_seconds: int = 0,
        ) -> int:
            raise AssertionError("send is not used")

        async def lease(
            self,
            queue_name: QueueName,
            *,
            visibility_timeout_seconds: int,
        ) -> LeasedMessage | None:
            return invalid_message

        async def extend_lease(
            self,
            queue_name: QueueName,
            message_id: int,
            *,
            visibility_timeout_seconds: int,
        ) -> None:
            raise AssertionError("extend is not used")

        async def archive(self, queue_name: QueueName, message_id: int) -> None:
            raise AssertionError("archive is not used")

        async def dead_letter(
            self,
            source_queue: QueueName,
            dead_letter_queue: QueueName,
            message: LeasedMessage,
            *,
            error_code: str,
        ) -> None:
            await queue.dead_letter(
                source_queue,
                dead_letter_queue,
                invalid_message,
                error_code=error_code,
            )

    loop = JobLoop(InvalidTransport(), handle, logger=logger)
    assert await loop.run_once() is True
    assert handled is False
    assert logger.events[-1][1]["error_code"] == "invalid_job_message"


def test_NFR_03_job_loop_config_rejects_unbounded_values() -> None:
    with pytest.raises(ValueError):
        JobLoopConfig(job_timeout_seconds=0)
