"""Worker-side relay for the transactional database outbox."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from mandate_worker.observability import get_logger


class AsyncOutboxDatabase(Protocol):
    async def fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object] | None: ...


class OutboxLogger(Protocol):
    def info(self, event: str, **kwargs: object) -> object: ...

    def warning(self, event: str, **kwargs: object) -> object: ...


@dataclass(slots=True)
class OutboxRelay:
    """Ask the atomic DB helper to dispatch at most one pending row."""

    database: AsyncOutboxDatabase
    logger: OutboxLogger | None = None

    async def run_once(self) -> bool:
        row = await self.database.fetch_one(
            "select * from private.dispatch_next_outbox()",
            (),
        )
        if row is None:
            return False
        logger = self.logger or get_logger()
        if row.get("dispatched") is True:
            logger.info(
                "outbox_dispatched",
                outbox_id=str(row.get("outbox_id")),
                queue_message_id=row.get("queue_message_id"),
            )
        else:
            logger.warning(
                "outbox_dispatch_failed",
                outbox_id=str(row.get("outbox_id")),
                error_code="queue_dispatch_failed",
            )
        return True

    async def run_forever(
        self,
        stop_event: asyncio.Event,
        *,
        poll_seconds: float = 2.0,
    ) -> None:
        if not 0 < poll_seconds <= 60:
            raise ValueError("poll_seconds must be between 0 and 60")
        while not stop_event.is_set():
            processed = await self.run_once()
            if processed:
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass
