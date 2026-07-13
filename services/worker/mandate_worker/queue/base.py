"""Queue contracts shared by durable and in-memory backends."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from mandate_schemas import JobMessage

ERROR_CODE_PATTERN = re.compile(r"^[a-z0-9_:-]{1,100}$")


class QueueName(StrEnum):
    """The only queues the MVP worker is allowed to access."""

    JOBS = "mandate_jobs"
    LIGHT_TASKS = "mandate_light_tasks"
    JOBS_DEAD_LETTER = "mandate_jobs_dlq"


class QueueError(RuntimeError):
    """Base exception for queue operations."""


class QueueMessageNotFoundError(QueueError):
    """Raised when a lease operation references a missing message."""


@dataclass(frozen=True, slots=True)
class LeasedMessage:
    """A leased transport message before shared-schema validation."""

    message_id: int
    read_count: int
    enqueued_at: datetime
    visible_at: datetime
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class DeadLetterRecord:
    """Sanitised audit metadata for a poison message.

    The original payload is intentionally excluded. A poison payload is not trusted
    to respect Mandate's identifier-only message contract and therefore must not be
    copied into another durable queue.
    """

    source_queue: QueueName
    source_message_id: int
    read_count: int
    error_code: str
    payload_sha256: str
    observed_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "sourceQueue": self.source_queue.value,
            "sourceMessageId": self.source_message_id,
            "readCount": self.read_count,
            "errorCode": self.error_code,
            "payloadSha256": self.payload_sha256,
            "observedAt": self.observed_at.astimezone(UTC).isoformat(),
        }


def make_dead_letter_record(
    source_queue: QueueName,
    message: LeasedMessage,
    error_code: str,
    *,
    observed_at: datetime | None = None,
) -> DeadLetterRecord:
    """Build non-sensitive DLQ metadata for an invalid or exhausted message."""

    canonical_payload = json.dumps(
        message.payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return DeadLetterRecord(
        source_queue=source_queue,
        source_message_id=message.message_id,
        read_count=message.read_count,
        error_code=(error_code if ERROR_CODE_PATTERN.fullmatch(error_code) else "queue_error"),
        payload_sha256=hashlib.sha256(canonical_payload).hexdigest(),
        observed_at=observed_at or datetime.now(UTC),
    )


class QueueAdapter(Protocol):
    """Backend-neutral, at-least-once queue interface (ADR-002)."""

    async def send(
        self,
        queue_name: QueueName,
        message: JobMessage,
        *,
        delay_seconds: int = 0,
    ) -> int: ...

    async def lease(
        self,
        queue_name: QueueName,
        *,
        visibility_timeout_seconds: int,
    ) -> LeasedMessage | None: ...

    async def extend_lease(
        self,
        queue_name: QueueName,
        message_id: int,
        *,
        visibility_timeout_seconds: int,
    ) -> None: ...

    async def archive(self, queue_name: QueueName, message_id: int) -> None: ...

    async def dead_letter(
        self,
        source_queue: QueueName,
        dead_letter_queue: QueueName,
        message: LeasedMessage,
        *,
        error_code: str,
    ) -> None: ...
