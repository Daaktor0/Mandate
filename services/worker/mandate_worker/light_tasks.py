"""Bounded consumer for identifier-only unpaid light tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from mandate_schemas import LightTaskMessage
from pydantic import ValidationError

from mandate_worker.observability import SYSTEM_TRACE_ID, get_logger, trace_context
from mandate_worker.queue import QueueAdapter, QueueName


class LightTaskLogger(Protocol):
    def info(self, event: str, **kwargs: object) -> object: ...

    def warning(self, event: str, **kwargs: object) -> object: ...


LightTaskHandler = Callable[[LightTaskMessage], Awaitable[None]]
LightTaskTerminalFailureHandler = Callable[[LightTaskMessage, str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class LightTaskLoopConfig:
    visibility_timeout_seconds: int = 120
    idle_poll_seconds: float = 1.0
    task_timeout_seconds: int = 300
    max_delivery_attempts: int = 4

    def __post_init__(self) -> None:
        if self.visibility_timeout_seconds <= 0:
            raise ValueError("visibility_timeout_seconds must be positive")
        if self.idle_poll_seconds <= 0:
            raise ValueError("idle_poll_seconds must be positive")
        if not 1 <= self.task_timeout_seconds <= 600:
            raise ValueError("task_timeout_seconds must be between 1 and 600")
        if self.max_delivery_attempts <= 0:
            raise ValueError("max_delivery_attempts must be positive")


class LightTaskLoop:
    """Validate, bound and archive one at-least-once light-task delivery."""

    def __init__(
        self,
        queue: QueueAdapter,
        handler: LightTaskHandler,
        *,
        config: LightTaskLoopConfig | None = None,
        logger: LightTaskLogger | None = None,
        terminal_failure_handler: LightTaskTerminalFailureHandler | None = None,
    ) -> None:
        self._queue = queue
        self._handler = handler
        self._config = config or LightTaskLoopConfig()
        self._logger = logger or get_logger()
        self._terminal_failure_handler = terminal_failure_handler

    async def run_once(self) -> bool:
        message = await self._queue.lease(
            QueueName.LIGHT_TASKS,
            visibility_timeout_seconds=self._config.visibility_timeout_seconds,
        )
        if message is None:
            return False

        try:
            task = LightTaskMessage.model_validate(message.payload)
        except ValidationError as error:
            await self._queue.dead_letter(
                QueueName.LIGHT_TASKS,
                QueueName.JOBS_DEAD_LETTER,
                message,
                error_code="invalid_light_task_message",
            )
            self._logger.warning(
                "light_task_dead_lettered",
                trace_id=SYSTEM_TRACE_ID,
                queue_message_id=message.message_id,
                read_count=message.read_count,
                error_code="invalid_light_task_message",
                validation_error_count=error.error_count(),
            )
            return True

        with trace_context(
            task.trace_id,
            task_id=str(task.task_id),
            report_request_id=str(task.report_request_id),
            queue_message_id=message.message_id,
        ):
            if message.read_count > self._config.max_delivery_attempts:
                if self._terminal_failure_handler is not None:
                    try:
                        await self._terminal_failure_handler(
                            task,
                            "max_light_task_deliveries_exceeded",
                        )
                    except Exception as error:
                        self._logger.warning(
                            "light_task_terminal_failure_deferred",
                            error_code="failure_persistence_failed",
                            error_class=type(error).__name__,
                        )
                        return True
                await self._queue.dead_letter(
                    QueueName.LIGHT_TASKS,
                    QueueName.JOBS_DEAD_LETTER,
                    message,
                    error_code="max_light_task_deliveries_exceeded",
                )
                self._logger.warning(
                    "light_task_dead_lettered",
                    read_count=message.read_count,
                    error_code="max_light_task_deliveries_exceeded",
                )
                return True

            self._logger.info("light_task_started", task_type=task.task_type.value)
            try:
                async with asyncio.timeout(self._config.task_timeout_seconds):
                    await self._handler(task)
            except TimeoutError:
                self._logger.warning(
                    "light_task_attempt_failed",
                    failure_state="resolving_entity",
                    error_code="light_task_timeout",
                )
                return True
            except Exception as error:
                self._logger.warning(
                    "light_task_attempt_failed",
                    failure_state="resolving_entity",
                    error_code="handler_error",
                    error_class=type(error).__name__,
                )
                return True

            await self._queue.archive(QueueName.LIGHT_TASKS, message.message_id)
            self._logger.info("light_task_archived", task_type=task.task_type.value)
            return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        self._logger.info("light_task_loop_started", trace_id=SYSTEM_TRACE_ID)
        while not stop_event.is_set():
            processed = await self.run_once()
            if not processed:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self._config.idle_poll_seconds
                    )
                except TimeoutError:
                    pass
        self._logger.info("light_task_loop_stopped", trace_id=SYSTEM_TRACE_ID)
