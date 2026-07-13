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

The entity-resolution crawler layers robots/terms/access-control decisions and its
15-page budget on this boundary. Later Playwright interception may add restrictions but
may not bypass this network policy. SafeFetcher never receives or sends user credentials
and does not implement paywall/CAPTCHA bypass behavior.

## Legal-page crawler boundary

`mandate_worker.entity_resolution.LegalPageCrawler` performs the Phase 1
company-controlled site inspection. It is sequential and deterministic: fetch
`robots.txt`, then inspect the submitted page and same-host/`www` legal links in the
specified priority order. It caps successful and failed page attempts at 15, discovered
candidates at 100, links read from one page at 250 and parseable HTML at 2 MiB. Published
crawl delays up to five seconds are respected; a longer delay, unavailable robots policy,
explicit automation prohibition, CAPTCHA, paywall or access-control response stops the
relevant access without a bypass attempt.

The crawler strips scripts and hidden markup, flags prompt-injection phrases, and emits
only typed disclosure contexts and a 4,000-character excerpt—never the raw HTML. Its
versioned deterministic extraction covers legal names and relationships, CIN, GSTIN,
registered office, copyright/data-controller names, NSE/BSE tickers, Indian ISINs and
LLP scope warnings. Every accepted page is marked company-controlled and retains a
content hash for later Evidence construction.

PDF annual-report/policy links are discovered and audited but not parsed. An opaque URL
that returns a PDF is discarded after SafeFetcher's bounded read. Per the ADR-011
amendment and security-precedence rule, PDF text extraction stays unreachable until the
malware-scan and sandbox parser boundary is implemented.

## Company-data provider boundary

`mandate_worker.providers.CompanyDataProvider` exposes only `search_by_name(legal_name)`
and `lookup_by_cin(cin)`. This narrow signature is the privacy allowlist: user identity,
firm, billing, letterhead and confidential matter data have no input field and cannot be
forwarded. Results retain only the public company fields needed for resolution, an exact
normalised CIN and bounded provider-call metadata; provider email, directors, filings,
charges and raw responses are discarded.

`DEMO_MODE=1` selects the validated synthetic fixture and makes zero provider calls. In
live mode, set `PROVIDER_COMPANY_DATA=attestr` and supply `ATTESTR_AUTH_TOKEN`; an absent
credential, an unconfigured/unknown provider or a request for fixtures outside demo mode
fails closed. The live adapter uses fixed Attestr v2 HTTPS endpoints, disables redirects
and environment proxies, caps responses at 1 MiB, timeouts at eight seconds, results at
20 and calls (including retry) at two. It searches exact legal names and requests master
data with charges and e-filings disabled. B5 remains open until credentials, commercial/
data-use review and the 30-company staging accuracy gate are complete.

Run the worker unit suite:

```bash
uv run pytest -q services/worker/tests
```
