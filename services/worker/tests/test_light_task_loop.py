from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from mandate_schemas import LightTaskMessage
from mandate_schemas.generated import LightTaskMessageTaskType
from mandate_worker.light_tasks import LightTaskLoop, LightTaskLoopConfig
from mandate_worker.queue import MemoryQueueAdapter, QueueName


@dataclass
class RecordingLogger:
    events: list[tuple[str, dict[str, object]]]

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def task() -> LightTaskMessage:
    return LightTaskMessage(
        schemaVersion=1,
        taskId=UUID("11111111-1111-4111-8111-111111111111"),
        taskType=LightTaskMessageTaskType.RESOLVE_ENTITY,
        reportRequestId=UUID("22222222-2222-4222-8222-222222222222"),
        userId=UUID("33333333-3333-4333-8333-333333333333"),
        attempt=1,
        traceId="trace-light-task-test",
    )


@pytest.mark.asyncio
async def test_ENTITY_03_light_task_loop_validates_handles_and_archives() -> None:
    queue = MemoryQueueAdapter()
    logger = RecordingLogger([])
    handled: list[LightTaskMessage] = []

    async def handle(message: LightTaskMessage) -> None:
        handled.append(message)

    message = task()
    await queue.send(QueueName.LIGHT_TASKS, message)
    loop = LightTaskLoop(queue, handle, logger=logger)

    assert await loop.run_once() is True
    assert handled == [message]
    assert await queue.snapshot(QueueName.LIGHT_TASKS) == ()
    assert [event for event, _ in logger.events] == [
        "light_task_started",
        "light_task_archived",
    ]


@pytest.mark.asyncio
async def test_NFR_01_light_task_failure_remains_for_visibility_retry() -> None:
    queue = MemoryQueueAdapter()
    logger = RecordingLogger([])

    async def fail(_message: LightTaskMessage) -> None:
        raise RuntimeError("synthetic failure")

    await queue.send(QueueName.LIGHT_TASKS, task())
    loop = LightTaskLoop(queue, fail, logger=logger)

    assert await loop.run_once() is True
    assert len(await queue.snapshot(QueueName.LIGHT_TASKS)) == 1
    assert logger.events[-1][1]["failure_state"] == "resolving_entity"


@pytest.mark.asyncio
async def test_NFR_01_light_task_persists_failure_before_dead_letter() -> None:
    clock = MutableClock(datetime(2026, 7, 13, tzinfo=UTC))
    queue = MemoryQueueAdapter(clock=clock)
    terminal: list[tuple[LightTaskMessage, str]] = []

    async def fail(_message: LightTaskMessage) -> None:
        raise RuntimeError("synthetic failure")

    async def persist_terminal(message: LightTaskMessage, error_code: str) -> None:
        terminal.append((message, error_code))

    await queue.send(QueueName.LIGHT_TASKS, task())
    loop = LightTaskLoop(
        queue,
        fail,
        config=LightTaskLoopConfig(visibility_timeout_seconds=1),
        logger=RecordingLogger([]),
        terminal_failure_handler=persist_terminal,
    )

    for _ in range(4):
        assert await loop.run_once() is True
        clock.advance(seconds=1)
    assert await loop.run_once() is True

    assert terminal == [(task(), "max_light_task_deliveries_exceeded")]
    assert await queue.snapshot(QueueName.LIGHT_TASKS) == ()
    assert len(await queue.snapshot(QueueName.JOBS_DEAD_LETTER)) == 1
