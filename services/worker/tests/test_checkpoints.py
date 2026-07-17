from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from mandate_schemas import JobMessage
from mandate_worker.checkpoints import (
    CheckpointedPipeline,
    CheckpointError,
    CheckpointRecord,
    MemoryCheckpointStore,
    payload_sha256,
)
from mandate_worker.job_loop import JobLoop, JobLoopConfig
from mandate_worker.queue import MemoryQueueAdapter, QueueName


@pytest.mark.asyncio
async def test_NFR_01_checkpoint_payload_is_canonical_and_idempotent(
    job_message: JobMessage,
) -> None:
    payload = {"claims": [{"evidenceIds": ["e-1"], "confidence": "high"}]}
    checkpoint = CheckpointRecord.create(job_message, "plan", payload)
    store = MemoryCheckpointStore()

    first = await store.write(checkpoint)
    second = await store.write(
        CheckpointRecord(
            job_id=checkpoint.job_id,
            stage=checkpoint.stage,
            attempt=checkpoint.attempt,
            schema_version=checkpoint.schema_version,
            payload={"claims": [{"confidence": "high", "evidenceIds": ["e-1"]}]},
            payload_hash=payload_sha256(payload),
            completed_at=checkpoint.completed_at,
        )
    )

    assert second == first
    assert await store.completed_stages(job_message.job_id, job_message.attempt) == {"plan"}


def test_NFR_01_checkpoint_rejects_integrity_and_sensitive_payloads(
    job_message: JobMessage,
) -> None:
    with pytest.raises(CheckpointError, match="hash_mismatch"):
        CheckpointRecord(
            job_id=job_message.job_id,
            stage="plan",
            attempt=job_message.attempt,
            schema_version=1,
            payload={"ok": True},
            payload_hash="0" * 64,
            completed_at=datetime.now(UTC),
        )

    with pytest.raises(CheckpointError, match="forbidden_field"):
        CheckpointRecord.create(job_message, "plan", {"raw_text": "must not persist"})


@pytest.mark.asyncio
async def test_NFR_01_checkpointed_pipeline_resumes_after_kill(
    job_message: JobMessage,
) -> None:
    stages = ("plan", "research_business", "research_industry")
    store = MemoryCheckpointStore()
    calls: list[str] = []
    fail_once = True

    async def run_stage(_job: JobMessage, stage: str) -> dict[str, object]:
        nonlocal fail_once
        calls.append(stage)
        if stage == "research_business" and fail_once:
            fail_once = False
            raise RuntimeError("simulated worker termination")
        return {"stage": stage, "evidenceIds": []}

    pipeline = CheckpointedPipeline(store, run_stage, stages=stages)
    with pytest.raises(RuntimeError, match="simulated worker termination"):
        await pipeline.run(job_message)

    await pipeline.run(job_message)

    assert calls == ["plan", "research_business", "research_business", "research_industry"]
    assert await store.completed_stages(job_message.job_id, job_message.attempt) == set(stages)


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.mark.asyncio
async def test_NFR_01_job_loop_pipeline_redelivery_resumes_from_checkpoint(
    job_message: JobMessage,
) -> None:
    clock = MutableClock(datetime(2026, 7, 17, tzinfo=UTC))
    queue = MemoryQueueAdapter(clock=clock)
    store = MemoryCheckpointStore()
    calls: list[str] = []
    fail_once = True

    async def run_stage(_job: JobMessage, stage: str) -> dict[str, object]:
        nonlocal fail_once
        calls.append(stage)
        if stage == "research_business" and fail_once:
            fail_once = False
            raise RuntimeError("simulated kill")
        return {"stage": stage}

    pipeline = CheckpointedPipeline(
        store,
        run_stage,
        stages=("plan", "research_business"),
    )
    await queue.send(QueueName.JOBS, job_message)
    loop = JobLoop(
        queue,
        pipeline=pipeline,
        config=JobLoopConfig(visibility_timeout_seconds=1),
    )

    assert await loop.run_once() is True
    assert len(await queue.snapshot(QueueName.JOBS)) == 1
    clock.advance(seconds=1)
    assert await loop.run_once() is True

    assert calls == ["plan", "research_business", "research_business"]
    assert await queue.snapshot(QueueName.JOBS) == ()
    assert await store.completed_stages(job_message.job_id, job_message.attempt) == {
        "plan",
        "research_business",
    }
