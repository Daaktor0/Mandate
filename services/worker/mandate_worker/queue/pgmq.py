"""pgmq-backed queue adapter using an injected least-privilege DB executor."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, cast

from mandate_schemas import JobMessage, LightTaskMessage

from mandate_worker.queue.base import (
    LeasedMessage,
    QueueError,
    QueueMessageNotFoundError,
    QueueName,
    make_dead_letter_record,
)


class AsyncQueueDatabase(Protocol):
    """Small DB boundary implemented by the worker's future connection pool.

    Every call must finish in its own short transaction (normally autocommit).
    pgmq ``set_vt`` is relative to PostgreSQL's transaction timestamp, so a
    heartbeat executed repeatedly inside one long-lived transaction would not
    move visibility forward.
    """

    async def fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object] | None: ...


class PgmqQueueAdapter:
    """QueueAdapter for pgmq 1.x's documented SQL functions."""

    def __init__(self, database: AsyncQueueDatabase) -> None:
        self._database = database

    async def send(
        self,
        queue_name: QueueName,
        message: JobMessage | LightTaskMessage,
        *,
        delay_seconds: int = 0,
    ) -> int:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        payload = json.dumps(
            message.model_dump(mode="json", by_alias=True),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        row = await self._database.fetch_one(
            """
            select sent.message_id
            from pgmq.send(%s, %s::jsonb, %s) as sent(message_id)
            """,
            (queue_name.value, payload, delay_seconds),
        )
        return self._required_int(row, "message_id", operation="send")

    async def lease(
        self,
        queue_name: QueueName,
        *,
        visibility_timeout_seconds: int,
    ) -> LeasedMessage | None:
        if visibility_timeout_seconds <= 0:
            raise ValueError("visibility_timeout_seconds must be positive")
        row = await self._database.fetch_one(
            """
            select msg_id, read_ct, enqueued_at, vt, message
            from pgmq.read(%s, %s, 1)
            """,
            (queue_name.value, visibility_timeout_seconds),
        )
        if row is None:
            return None
        return LeasedMessage(
            message_id=self._required_int(row, "msg_id", operation="lease"),
            read_count=self._required_int(row, "read_ct", operation="lease"),
            enqueued_at=self._required_datetime(row, "enqueued_at"),
            visible_at=self._required_datetime(row, "vt"),
            payload=self._required_payload(row),
        )

    async def extend_lease(
        self,
        queue_name: QueueName,
        message_id: int,
        *,
        visibility_timeout_seconds: int,
    ) -> None:
        if visibility_timeout_seconds <= 0:
            raise ValueError("visibility_timeout_seconds must be positive")
        row = await self._database.fetch_one(
            """
            select (pgmq.set_vt(%s, %s, %s)).msg_id as message_id
            """,
            (queue_name.value, message_id, visibility_timeout_seconds),
        )
        updated_id = self._required_int(row, "message_id", operation="extend_lease")
        if updated_id != message_id:
            raise QueueError("pgmq extended an unexpected message")

    async def archive(self, queue_name: QueueName, message_id: int) -> None:
        row = await self._database.fetch_one(
            "select pgmq.archive(%s, %s) as archived",
            (queue_name.value, message_id),
        )
        if row is None or row.get("archived") is not True:
            raise QueueMessageNotFoundError(f"message {message_id} does not exist")

    async def dead_letter(
        self,
        source_queue: QueueName,
        dead_letter_queue: QueueName,
        message: LeasedMessage,
        *,
        error_code: str,
    ) -> None:
        record = make_dead_letter_record(source_queue, message, error_code)
        payload = json.dumps(
            record.as_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        row = await self._database.fetch_one(
            """
            with dead_letter as (
              select sent.message_id
              from pgmq.send(%s, %s::jsonb, 0) as sent(message_id)
            )
            select pgmq.archive(%s, %s) as archived
            from dead_letter
            """,
            (
                dead_letter_queue.value,
                payload,
                source_queue.value,
                message.message_id,
            ),
        )
        if row is None or row.get("archived") is not True:
            raise QueueMessageNotFoundError(
                f"message {message.message_id} could not be dead-lettered"
            )

    @staticmethod
    def _required_int(
        row: Mapping[str, object] | None,
        key: str,
        *,
        operation: str,
    ) -> int:
        if row is None:
            raise QueueError(f"pgmq {operation} returned no row")
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise QueueError(f"pgmq {operation} returned an invalid {key}")
        return value

    @staticmethod
    def _required_datetime(row: Mapping[str, object], key: str) -> datetime:
        value = row.get(key)
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise QueueError(f"pgmq lease returned an invalid {key}") from error
        else:
            raise QueueError(f"pgmq lease returned an invalid {key}")
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _required_payload(row: Mapping[str, object]) -> dict[str, object]:
        value = row.get("message")
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as error:
                raise QueueError("pgmq lease returned invalid JSON") from error
        else:
            decoded = value
        if not isinstance(decoded, Mapping) or not all(isinstance(key, str) for key in decoded):
            raise QueueError("pgmq lease returned a non-object message")
        return dict(cast(Mapping[str, object], decoded))
