# Phase 2 security review — checkpointing and resume

**Scope:** ordered worker stages, `job_checkpoints` integrity, queue redelivery and lease renewal.

The slice adds the worker-side completion boundary required by `QUEUE-AND-JOB-SPEC.md`.
Only allowlisted stages can execute. A stage result is validated as bounded JSON,
canonicalised, SHA-256 hashed and written after successful completion. The worker
never archives the queue message before the pipeline has written all checkpoints.

| Threat | Control | Evidence |
|---|---|---|
| A restart repeats completed work | Store lookup skips completed `(job_id, stage, attempt)` rows before running a stage | `test_NFR_01_checkpointed_pipeline_resumes_after_kill`; `test_NFR_01_job_loop_pipeline_redelivery_resumes_from_checkpoint` |
| A duplicate write changes a completed result | Unique-key semantics return the original record only for the same digest and reject a different digest | `test_NFR_01_checkpoint_payload_is_canonical_and_idempotent` |
| Checkpoint data is tampered with | Canonical JSON is bounded and its supplied digest is recomputed before acceptance | `test_NFR_01_checkpoint_rejects_integrity_and_sensitive_payloads` |
| Sensitive or untrusted source data is persisted | Raw bodies, raw text, prompts, credentials, letterhead and matter narrative keys are rejected; checkpoint values are never provider payloads | checkpoint payload validation and worker README boundary |
| A long stage loses its lease and runs concurrently | The job loop renews the queue lease at most every 60 seconds and keeps the existing visibility retry/DLQ behavior | `_lease_heartbeat` in `job_loop.py`; queue adapter contract |
| A cancelled stage is falsely marked complete | The checkpoint write occurs after the awaited stage result; cancellation or exception exits before the write | kill-and-resume test |

The durable SQL migration remains the authoritative production sink: forced RLS,
service-role-only grants, a unique `(job_id, stage, attempt)` constraint and the
bounded JSON/hash checks apply when the worker database adapter is wired. The memory
store is fixture-only and does not enable live providers or persistence by itself.
