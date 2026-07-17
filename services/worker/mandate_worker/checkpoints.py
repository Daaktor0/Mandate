"""Validated stage checkpoints and restart-safe pipeline execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from mandate_schemas import JobMessage

CHECKPOINT_SCHEMA_VERSION = 1
MAX_CHECKPOINT_BYTES = 256 * 1024
PIPELINE_STAGES: tuple[str, ...] = (
    "plan",
    "research_business",
    "research_industry",
    "research_competitors",
    "research_corporate",
    "research_regulatory",
    "research_public_risk",
    "verify_contradictions",
    "analyze_transaction_prep",
    "compose_brief",
    "final_verify",
    "render_pdf",
    "deliver",
)
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "letterhead",
        "matter_narrative",
        "password",
        "raw_body",
        "raw_html",
        "raw_text",
        "secret",
        "set_cookie",
        "user_email",
    }
)


class CheckpointError(ValueError):
    """Raised when a checkpoint violates the durable contract."""


def _validate_json_value(value: object, *, path: str = "payload") -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CheckpointError(f"{path}_key_invalid")
            if key.casefold() in _FORBIDDEN_KEYS:
                raise CheckpointError(f"{path}_contains_forbidden_field")
            _validate_json_value(child, path=f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, child in enumerate(value):
            _validate_json_value(child, path=f"{path}[{index}]")
        return
    raise CheckpointError(f"{path}_value_not_json")


def canonical_payload(payload: Mapping[str, object]) -> bytes:
    """Validate and serialise a stage output exactly as it is hashed."""

    _validate_json_value(payload)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CheckpointError("payload_not_serializable") from error
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise CheckpointError("payload_too_large")
    return encoded


def payload_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    """A completed, validated stage output with its integrity digest."""

    job_id: UUID
    stage: str
    attempt: int
    schema_version: int
    payload: Mapping[str, object]
    payload_hash: str
    completed_at: datetime

    def __post_init__(self) -> None:
        if self.stage not in PIPELINE_STAGES:
            raise CheckpointError("checkpoint_stage_not_allowlisted")
        if not 1 <= self.attempt <= 100:
            raise CheckpointError("checkpoint_attempt_invalid")
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointError("checkpoint_schema_version_unsupported")
        expected = payload_sha256(self.payload)
        if self.payload_hash != expected:
            raise CheckpointError("checkpoint_payload_hash_mismatch")
        if self.completed_at.tzinfo is None:
            raise CheckpointError("checkpoint_timestamp_must_be_timezone_aware")

    @classmethod
    def create(
        cls,
        job: JobMessage,
        stage: str,
        payload: Mapping[str, object],
    ) -> CheckpointRecord:
        canonical_payload(payload)
        return cls(
            job_id=job.job_id,
            stage=stage,
            attempt=job.attempt,
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            payload=dict(payload),
            payload_hash=payload_sha256(payload),
            completed_at=datetime.now(UTC),
        )


class CheckpointStore(Protocol):
    async def completed_stages(self, job_id: UUID, attempt: int) -> frozenset[str]: ...

    async def write(self, checkpoint: CheckpointRecord) -> CheckpointRecord: ...


class MemoryCheckpointStore:
    """Deterministic fixture store with the same idempotency rules as SQL."""

    def __init__(self) -> None:
        self._records: dict[tuple[UUID, str, int], CheckpointRecord] = {}
        self._lock = asyncio.Lock()

    async def completed_stages(self, job_id: UUID, attempt: int) -> frozenset[str]:
        async with self._lock:
            return frozenset(
                stage
                for (stored_job_id, stage, stored_attempt) in self._records
                if stored_job_id == job_id and stored_attempt == attempt
            )

    async def write(self, checkpoint: CheckpointRecord) -> CheckpointRecord:
        key = (checkpoint.job_id, checkpoint.stage, checkpoint.attempt)
        async with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing.payload_hash != checkpoint.payload_hash:
                    raise CheckpointError("checkpoint_duplicate_payload_mismatch")
                return existing
            self._records[key] = checkpoint
            return checkpoint

    async def records_for(self, job_id: UUID, attempt: int) -> tuple[CheckpointRecord, ...]:
        async with self._lock:
            return tuple(
                record
                for (stored_job_id, _stage, stored_attempt), record in self._records.items()
                if stored_job_id == job_id and stored_attempt == attempt
            )


StageRunner = Callable[[JobMessage, str], Awaitable[Mapping[str, object]]]


class CheckpointedPipeline:
    """Run ordered stages and persist each result before advancing."""

    def __init__(
        self,
        store: CheckpointStore,
        stage_runner: StageRunner,
        *,
        stages: tuple[str, ...] = PIPELINE_STAGES,
    ) -> None:
        if not stages or any(stage not in PIPELINE_STAGES for stage in stages):
            raise ValueError("pipeline stages must be allowlisted")
        if tuple(sorted(stages, key=PIPELINE_STAGES.index)) != stages:
            raise ValueError("pipeline stages must be ordered")
        self._store = store
        self._stage_runner = stage_runner
        self._stages = stages

    async def run(self, job: JobMessage) -> None:
        completed = await self._store.completed_stages(job.job_id, job.attempt)
        for stage in self._stages:
            if stage in completed:
                continue
            output = await self._stage_runner(job, stage)
            if not isinstance(output, Mapping):
                raise CheckpointError("stage_output_must_be_object")
            checkpoint = CheckpointRecord.create(job, stage, output)
            await self._store.write(checkpoint)
