"""Bounded queue-consumer shell; pipeline stages arrive in later phases."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from mandate_schemas import JobMessage
from pydantic import ValidationError

from mandate_worker.observability import SYSTEM_TRACE_ID, get_logger, trace_context
from mandate_worker.queue import QueueAdapter, QueueName


class WorkerLogger(Protocol):
    def info(self, event: str, **kwargs: object) -> object: ...

    def warning(self, event: str, **kwargs: object) -> object: ...


JobHandler = Callable[[JobMessage], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class JobLoopConfig:
    queue_name: QueueName = QueueName.JOBS
    dead_letter_queue: QueueName = QueueName.JOBS_DEAD_LETTER
    visibility_timeout_seconds: int = 120
    idle_poll_seconds: float = 1.0
    job_timeout_seconds: int = 1_200
    max_delivery_attempts: int = 4

    def __post_init__(self) -> None:
        if self.visibility_timeout_seconds <= 0:
            raise ValueError("visibility_timeout_seconds must be positive")
        if self.idle_poll_seconds <= 0:
            raise ValueError("idle_poll_seconds must be positive")
        if self.job_timeout_seconds <= 0:
            raise ValueError("job_timeout_seconds must be positive")
        if self.max_delivery_attempts <= 0:
            raise ValueError("max_delivery_attempts must be positive")


class JobLoop:
    """Lease, validate, bound, audit and archive one message at a time."""

    def __init__(
        self,
        queue: QueueAdapter,
        handler: JobHandler,
        *,
        config: JobLoopConfig | None = None,
        logger: WorkerLogger | None = None,
    ) -> None:
        self._queue = queue
        self._handler = handler
        self._config = config or JobLoopConfig()
        self._logger = logger or get_logger()

    async def run_once(self) -> bool:
        """Process at most one delivery; return whether a message was leased."""

        message = await self._queue.lease(
            self._config.queue_name,
            visibility_timeout_seconds=self._config.visibility_timeout_seconds,
        )
        if message is None:
            return False

        try:
            job = JobMessage.model_validate(message.payload)
        except ValidationError as error:
            await self._queue.dead_letter(
                self._config.queue_name,
                self._config.dead_letter_queue,
                message,
                error_code="invalid_job_message",
            )
            self._logger.warning(
                "job_dead_lettered",
                trace_id=SYSTEM_TRACE_ID,
                queue_message_id=message.message_id,
                read_count=message.read_count,
                error_code="invalid_job_message",
                validation_error_count=error.error_count(),
            )
            return True

        with trace_context(
            job.trace_id,
            job_id=str(job.job_id),
            report_request_id=str(job.report_request_id),
            queue_message_id=message.message_id,
        ):
            if message.read_count > self._config.max_delivery_attempts:
                await self._queue.dead_letter(
                    self._config.queue_name,
                    self._config.dead_letter_queue,
                    message,
                    error_code="max_deliveries_exceeded",
                )
                self._logger.warning(
                    "job_dead_lettered",
                    read_count=message.read_count,
                    error_code="max_deliveries_exceeded",
                )
                return True

            self._logger.info("job_started", attempt=job.attempt)
            try:
                async with asyncio.timeout(self._config.job_timeout_seconds):
                    await self._handler(job)
            except TimeoutError:
                self._logger.warning(
                    "job_attempt_failed",
                    failure_state="retry_wait",
                    error_code="job_timeout",
                )
                return True
            except Exception as error:
                self._logger.warning(
                    "job_attempt_failed",
                    failure_state="retry_wait",
                    error_code="handler_error",
                    error_class=type(error).__name__,
                )
                return True

            await self._queue.archive(self._config.queue_name, message.message_id)
            self._logger.info("job_archived", attempt=job.attempt)
            return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Poll until shutdown without an uninterruptible sleep."""

        self._logger.info("job_loop_started", trace_id=SYSTEM_TRACE_ID)
        while not stop_event.is_set():
            processed = await self.run_once()
            if not processed:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self._config.idle_poll_seconds
                    )
                except TimeoutError:
                    pass
        self._logger.info("job_loop_stopped", trace_id=SYSTEM_TRACE_ID)
