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

## Search-provider boundary

`mandate_worker.providers.SearchProvider` discovers public-web URLs; it does not fetch
pages or create evidence. `SearchRequest` accepts only a bounded public query, result
limit, domain filters and timezone-aware publication-date filters. Account, firm,
billing, letterhead and confidential matter fields are structurally rejected.

`DEMO_MODE=1` selects the pinned synthetic search fixture and makes zero provider calls.
In live mode, set `PROVIDER_SEARCH=exa` and supply `EXA_API_KEY`. The Exa adapter calls
only the fixed `POST https://api.exa.ai/search` endpoint, disables redirects and
environment proxies, requests extractive highlights rather than generated summaries or
full-page text, caps results at 20, provider calls at two, responses at 2 MiB and each
timeout at ten seconds, and retains Exa's reported cost for later report attribution.
Missing credentials, fixture selection outside demo mode and unknown providers fail
closed without fallback.

Every returned URL remains untrusted discovery metadata. Credentials and non-default
ports are rejected, fragments are stripped and duplicate canonical URLs are removed.
Before any result can support a claim, a later `PageFetcher` stage must retrieve it
through `SafeFetcher`, capture provenance and pass source-tier and evidence validation.
Exa is not a company-master-data or MCA-filing provider.

## Company-data provider boundary

`mandate_worker.providers.CompanyDataProvider` exposes only `search_by_name(legal_name)`
and `lookup_by_cin(cin)`. This narrow signature is the privacy allowlist: user identity,
firm, billing, letterhead and confidential matter data have no input field and cannot be
forwarded. Results retain only the public company fields needed for resolution, an exact
normalised CIN and bounded provider-call metadata; provider email, directors, filings,
charges and raw responses are discarded.

`DEMO_MODE=1` selects the validated synthetic fixture and makes zero provider calls. No
live company-master-data provider is currently allowlisted. The earlier Attestr assumption
was not supported by its current product catalogue; selecting
`PROVIDER_COMPANY_DATA=attestr` now stops worker startup. The old adapter implementation
is retained only as quarantined historical code until it can be removed in a dedicated
cleanup without weakening the generic interface or fixture tests.

The live Phase 1 benchmark remains open. Candidate sources are a versioned MCA-contributed
Government Open Data snapshot and, only after current API/licence verification, providers
such as Sandbox or Probe42. See
[`B5-mca-data-and-document-acquisition.md`](../../docs/implementation/spikes/B5-mca-data-and-document-acquisition.md).

## Corporate-filing document acquisition boundary

`mandate_worker.providers.CorporateFilingDocumentProvider` is separate from master data and
public-web search. It supports three explicit outcomes: quarantined documents are ready,
a human MCA View Public Documents purchase is required, or the filing is unavailable.

`ManualMcaVpdProvider` performs no network request and accepts no MCA credentials. It emits
`mca_vpd_login_payment_required` so an authorised operator can procure selected public
filings outside Mandate and import them through a future admin-only acquisition surface.
A later licensed-provider implementation may replace that step after provenance, coverage,
storage/display rights, pricing and security are verified.

Every imported PDF/ZIP is SHA-256-addressed, size bounded and registered as
`pending_malware_scan` with `parse_allowed=false`. No filing text may reach extraction,
evidence or a model until the reusable malware-scan and sandbox parser boundary is built.
Source locators reject embedded password/token/API-key material.

## Candidate-generation and scoring boundary

`mandate_worker.entity_resolution.EntityCandidateGenerator` consumes the typed site
inspection, the `CompanyDataProvider` and pre-classified public-source signals. It looks
up supplied/extracted CINs before exact legal names, normalises duplicate names, dedupes
records by CIN and ranks at most 20 generated `EntityCandidate` contracts. Candidate and
evidence IDs are deterministic UUIDv5 values; candidate IDs include the report-request
id so retries remain stable without colliding when the same company is a candidate for
different requests.

The scorer applies the doc 05 table verbatim: positive weights 35/20/15/15/10/5 and
negative adjustments −15/−10/−15/−20/−10, floored at zero. Labels are derived only from
the ≥75, 50–74, 25–49 and <25 thresholds. Each candidate has bounded evidence snippets,
user-facing conflicts and an `entity-confidence-v1` factor audit with concise rationale
codes—no model output or hidden reasoning. The result always contains
`requiresUserConfirmation=true`; there is no auto-selected-candidate field. A no-match
result returns `legal_name_or_cin_required`.

Address matching is deliberately conservative: the master-data state must match and at
least three meaningful address tokens must overlap at a ratio of 0.5 or more. A negative
office conflict is applied automatically only when both sides expose different recognised
Indian states; other address uncertainty remains unscored unless a verified source signal
marks a conflict. Candidate generation is sequential and capped at 10 CIN queries, 10
name queries, 20 provider operations (40 network calls including the provider's two-call
retry cap), 20 candidates and 20 evidence snippets per candidate.

## Entity-resolution persistence and light tasks

`LightTaskMessage` is a generated, identifier-only contract for unpaid short work. The
web commits `draft → resolving_entity` and an outbox row in one RPC; `OutboxRelay` invokes
the worker-only atomic dispatch helper, and `LightTaskLoop` validates the payload again,
applies a five-minute timeout and leaves transient failures for visibility retry.

`EntityResolutionTaskHandler` loads only the request identifiers/public input needed by
the provider/crawler, generates request-scoped deterministic candidates and calls one
database completion function that upserts shared entities, stores ranked candidates and
factor audits, then changes the state to `awaiting_entity_confirmation`. Empty results,
non-retryable failures and exhausted delivery retries become `failed_no_charge`; the
terminal failure is persisted before dead-lettering. Replays are state-idempotent. No
path references entitlements, confirms a candidate or starts paid research.

Run the worker unit suite:

```bash
uv run pytest -q services/worker/tests
```
