from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest
from mandate_worker.outbox import OutboxRelay


@dataclass
class RecordingDatabase:
    row: Mapping[str, object] | None
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    async def fetch_one(
        self, statement: str, parameters: tuple[object, ...]
    ) -> Mapping[str, object] | None:
        self.calls.append((statement, parameters))
        return self.row


@pytest.mark.asyncio
async def test_NFR_01_outbox_relay_uses_atomic_dispatch_helper() -> None:
    database = RecordingDatabase(
        {"outbox_id": "outbox-1", "queue_message_id": 7, "dispatched": True}
    )
    relay = OutboxRelay(database)

    assert await relay.run_once() is True
    assert database.calls == [("select * from private.dispatch_next_outbox()", ())]


@pytest.mark.asyncio
async def test_NFR_01_outbox_relay_reports_idle_without_writes() -> None:
    relay = OutboxRelay(RecordingDatabase(None))

    assert await relay.run_once() is False
