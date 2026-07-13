"""Deterministic in-memory queue for tests and zero-spend demo mode."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from mandate_schemas import JobMessage

from mandate_worker.queue.base import (
    LeasedMessage,
    QueueMessageNotFoundError,
    QueueName,
    make_dead_letter_record,
)


@dataclass(slots=True)
class _StoredMessage:
    message_id: int
    read_count: int
    enqueued_at: datetime
    visible_at: datetime
    payload: dict[str, object]

    def leased(self) -> LeasedMessage:
        return LeasedMessage(
            message_id=self.message_id,
            read_count=self.read_count,
            enqueued_at=self.enqueued_at,
            visible_at=self.visible_at,
            payload=dict(self.payload),
        )


class MemoryQueueAdapter:
    """An asyncio-safe pgmq semantic subset with injectable time."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()
        self._next_message_id = 1
        self._messages: dict[QueueName, dict[int, _StoredMessage]] = {
            queue: {} for queue in QueueName
        }
        self._archive: dict[QueueName, dict[int, _StoredMessage]] = {
            queue: {} for queue in QueueName
        }

    async def send(
        self,
        queue_name: QueueName,
        message: JobMessage,
        *,
        delay_seconds: int = 0,
    ) -> int:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        payload = message.model_dump(mode="json", by_alias=True)
        async with self._lock:
            return self._enqueue(queue_name, payload, delay_seconds=delay_seconds)

    async def lease(
        self,
        queue_name: QueueName,
        *,
        visibility_timeout_seconds: int,
    ) -> LeasedMessage | None:
        if visibility_timeout_seconds <= 0:
            raise ValueError("visibility_timeout_seconds must be positive")
        async with self._lock:
            now = self._clock()
            available = [
                message
                for message in self._messages[queue_name].values()
                if message.visible_at <= now
            ]
            if not available:
                return None
            message = min(available, key=lambda item: item.message_id)
            message.read_count += 1
            message.visible_at = now + timedelta(seconds=visibility_timeout_seconds)
            return message.leased()

    async def extend_lease(
        self,
        queue_name: QueueName,
        message_id: int,
        *,
        visibility_timeout_seconds: int,
    ) -> None:
        if visibility_timeout_seconds <= 0:
            raise ValueError("visibility_timeout_seconds must be positive")
        async with self._lock:
            message = self._messages[queue_name].get(message_id)
            if message is None:
                raise QueueMessageNotFoundError(f"message {message_id} does not exist")
            message.visible_at = self._clock() + timedelta(seconds=visibility_timeout_seconds)

    async def archive(self, queue_name: QueueName, message_id: int) -> None:
        async with self._lock:
            message = self._messages[queue_name].pop(message_id, None)
            if message is None:
                raise QueueMessageNotFoundError(f"message {message_id} does not exist")
            self._archive[queue_name][message_id] = message

    async def dead_letter(
        self,
        source_queue: QueueName,
        dead_letter_queue: QueueName,
        message: LeasedMessage,
        *,
        error_code: str,
    ) -> None:
        async with self._lock:
            stored = self._messages[source_queue].pop(message.message_id, None)
            if stored is None:
                raise QueueMessageNotFoundError(f"message {message.message_id} does not exist")
            record = make_dead_letter_record(
                source_queue,
                message,
                error_code,
                observed_at=self._clock(),
            )
            self._enqueue(dead_letter_queue, record.as_dict(), delay_seconds=0)
            self._archive[source_queue][message.message_id] = stored

    async def snapshot(self, queue_name: QueueName) -> tuple[LeasedMessage, ...]:
        """Return a defensive snapshot for tests and demo diagnostics."""

        async with self._lock:
            return tuple(
                message.leased()
                for message in sorted(
                    self._messages[queue_name].values(),
                    key=lambda item: item.message_id,
                )
            )

    def _enqueue(
        self,
        queue_name: QueueName,
        payload: dict[str, object],
        *,
        delay_seconds: int,
    ) -> int:
        now = self._clock()
        message_id = self._next_message_id
        self._next_message_id += 1
        self._messages[queue_name][message_id] = _StoredMessage(
            message_id=message_id,
            read_count=0,
            enqueued_at=now,
            visible_at=now + timedelta(seconds=delay_seconds),
            payload=dict(payload),
        )
        return message_id
