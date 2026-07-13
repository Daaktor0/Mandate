# Worker service

This directory owns the queued Mandate research, verification, composition and rendering service (SYSTEM-SPEC C6–C10).

The worker is stateless between checkpoints, uses typed provider adapters, and must remain runnable in `DEMO_MODE=1` without external credentials or API spend.

## Phase 0 runtime foundation

- `mandate_worker.main:app` exposes the internal FastAPI `GET /health` endpoint.
- `JobLoop` leases one identifier-only `JobMessage` at a time, validates it against the generated Pydantic contract, applies a 1,200-second hard timeout, archives success and leaves transient failure for visibility-timeout retry.
- `MemoryQueueAdapter` provides deterministic pgmq-like semantics for tests and `DEMO_MODE=1`.
- `PgmqQueueAdapter` uses the documented `pgmq.send`, `read`, `set_vt` and `archive` functions through an injected least-privilege database boundary.
- Poison-message DLQ records contain a payload hash and audit metadata, never the untrusted payload itself.
- Structured JSON logging supplies a `trace_id` on every event; job events bind the message's trace and identifier-only audit fields.

The database pool and process supervisor are wired in the later container/deployment tasks. No provider credentials or model routes are required for this slice.

Run the worker unit suite:

```bash
uv run pytest -q services/worker/tests
```
