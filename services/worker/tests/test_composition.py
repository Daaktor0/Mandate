from __future__ import annotations

import asyncio
import threading
import time
from typing import cast

import pytest
from fastapi.testclient import TestClient
from mandate_schemas import LightTaskMessage
from mandate_worker.composition import LightTaskRuntimeDependencies
from mandate_worker.entity_resolution.task import EntityResolutionTaskHandler
from mandate_worker.light_tasks import LightTaskLoopConfig
from mandate_worker.main import create_app
from mandate_worker.preliminary_research import PreliminaryResearchTaskHandler
from mandate_worker.queue import LeasedMessage, MemoryQueueAdapter, QueueName
from mandate_worker.runtime import RuntimeConfigurationError


class RecordingMemoryQueueAdapter(MemoryQueueAdapter):
    def __init__(self, *, minimum_polls: int = 2) -> None:
        super().__init__()
        self._minimum_polls = minimum_polls
        self._poll_lock = threading.Lock()
        self._polls = 0
        self.polled = threading.Event()

    @property
    def polls(self) -> int:
        with self._poll_lock:
            return self._polls

    async def lease(
        self,
        queue_name: QueueName,
        *,
        visibility_timeout_seconds: int,
    ) -> LeasedMessage | None:
        leased = await super().lease(
            queue_name,
            visibility_timeout_seconds=visibility_timeout_seconds,
        )
        with self._poll_lock:
            self._polls += 1
            if self._polls >= self._minimum_polls:
                self.polled.set()
        return leased


class NoopLightTaskHandler:
    async def __call__(self, _message: LightTaskMessage) -> None:
        return None

    async def fail_terminal(self, _message: LightTaskMessage, _error_code: str) -> None:
        return None


def _light_task_config() -> LightTaskLoopConfig:
    return LightTaskLoopConfig(
        visibility_timeout_seconds=1,
        idle_poll_seconds=0.01,
        task_timeout_seconds=1,
        max_delivery_attempts=1,
    )


def test_NFR_01_worker_starts_no_light_task_loops_without_factory() -> None:
    with TestClient(create_app(environ={})) as client:
        response = client.get("/health")
        runtime = client.app.state.light_task_runtime

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert runtime.configuration.enabled is False
    assert runtime.tasks == ()


def test_NFR_01_worker_starts_and_stops_injected_light_task_loops() -> None:
    queues: list[RecordingMemoryQueueAdapter] = []
    tasks: tuple[asyncio.Task[None], ...] = ()

    def factory() -> LightTaskRuntimeDependencies:
        queue = RecordingMemoryQueueAdapter()
        queues.append(queue)
        handler = NoopLightTaskHandler()
        return LightTaskRuntimeDependencies(
            queue=queue,
            preliminary_research_handler=cast(PreliminaryResearchTaskHandler, handler),
            entity_resolution_handler=cast(EntityResolutionTaskHandler, handler),
            preliminary_research_config=_light_task_config(),
            entity_resolution_config=_light_task_config(),
        )

    with TestClient(create_app(environ={}, light_task_dependencies_factory=factory)) as client:
        assert client.get("/health").status_code == 200
        queue = queues[0]
        tasks = client.app.state.light_task_loop_tasks
        deadline = time.monotonic() + 2
        while queue.polls < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        task_state = [
            (task.done(), None if not task.done() else repr(task.exception())) for task in tasks
        ]
        assert queue.polls >= 2, task_state
        assert len(tasks) == 2
        assert all(not task.done() for task in tasks)

    assert all(task.done() for task in tasks)
    assert all(task.exception() is None for task in tasks)


def test_NFR_01_worker_fails_closed_when_light_task_factory_fails() -> None:
    def factory() -> LightTaskRuntimeDependencies:
        raise RuntimeConfigurationError("synthetic dependency failure")

    with pytest.raises(RuntimeConfigurationError, match="synthetic dependency failure"):
        with TestClient(create_app(environ={}, light_task_dependencies_factory=factory)):
            pass
