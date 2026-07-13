# Worker service

This directory owns the queued Mandate research, verification, composition and rendering service (SYSTEM-SPEC C6–C10).

The worker is stateless between checkpoints, uses typed provider adapters, and must remain runnable in `DEMO_MODE=1` without external credentials or API spend.

## Phase 0 runtime foundation

- `mandate_worker.main:app` exposes the internal FastAPI `GET /health` endpoint.
- `JobLoop` leases one identifier-only `JobMessage` at a time, validates it against the generated Pydantic contract, applies a 1,200-second hard timeout, archives success and leaves transient failure for visibility-timeout retry.
- `MemoryQueueAdapter` provides deterministic pgmq-like semantics for tests and `DEMO_MODE=1`.
- `build_runtime_adapter_plan` forces every C8 capability to its fixture, memory,
  or console implementation when `DEMO_MODE=1`; conflicting live-provider selectors
  are ignored by name and never logged with their values.
- `FixtureCatalog` validates the complete synthetic catalog and every SHA-256 before
  the worker starts in demo mode. The renderer does not initialise provider wiring.
- `PgmqQueueAdapter` uses the documented `pgmq.send`, `read`, `set_vt` and `archive` functions through an injected least-privilege database boundary.
- Each pgmq call must use a short committed/autocommit transaction. `set_vt` is relative to PostgreSQL's transaction timestamp, so lease heartbeats must never share the job's long-running transaction.
- Poison-message DLQ records contain a payload hash and audit metadata, never the untrusted payload itself.
- Structured JSON logging supplies a `trace_id` on every event; job events bind the message's trace and identifier-only audit fields. A recursive sink processor redacts secrets, identity, prompts, work product, raw content, exception detail and binary values while retaining approved audit metadata.

The database pool and process supervisor are wired in the later container/deployment tasks. No provider credentials or model routes are required for this slice.

## SafeFetcher boundary

All outbound public-page retrieval must use `mandate_worker.fetch.SafeFetcher`; callers
must not construct an HTTP client directly. For every request, redirect and retry it:

- accepts only canonical HTTP/HTTPS URLs on their default ports and rejects URL
  credentials, credential-like query keys and non-public hostnames;
- resolves once for that network attempt, rejects the complete DNS answer set if any
  address is non-public, and connects to the selected vetted IP with the original Host
  header and TLS SNI;
- creates an isolated proxy-free, cookie-free connection, disables automatic redirects
  and response decompression, and re-runs policy before every subsequent hop;
- caps redirects at five, attempts at two, response bodies at 10 MiB and each timeout at
  the configured value; and
- returns stable failure codes plus only the canonical URL, final vetted IP, redirect
  chain and response metadata needed for later audit records.

Robots/ToS decisions, the 15-page entity-resolution crawl budget and Playwright request
interception belong to the immediately following crawler/browser slices. They may add
restrictions but may not bypass this network policy. SafeFetcher never receives or sends
user credentials and does not implement paywall/CAPTCHA bypass behavior.

Run the worker unit suite:

```bash
uv run pytest -q services/worker/tests
```
