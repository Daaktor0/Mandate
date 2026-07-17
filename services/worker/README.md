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
Before any result can support a claim, the PageFetcher stage must retrieve it through
`SafeFetcher`; source-tier classification and evidence admission still occur later.
Exa is not a company-master-data or MCA-filing provider.

## PageFetcher boundary

`mandate_worker.providers.PageFetcher` turns one public URL into bounded extracted text
and provenance without admitting the result as evidence. `PageFetchRequest` accepts only
the canonical URL. User identity, firm, billing, prompts, answers, letterhead and
confidential matter narrative have no input field.

The live `SafePageFetcher` retrieves and evaluates `robots.txt` before fetching the page,
respects published crawl delays up to five seconds and delegates every network operation
to the DNS/IP-pinned `SafeFetcher`. Robots denial or unavailability, off-site robots
redirects, excessive delays, CAPTCHA, paywall and explicit automation restrictions stop
the operation without a bypass attempt. Fixture mode is deterministic and zero-network;
unknown or unconfigured bindings fail closed.

For bounded HTML, XHTML, XML and plain text, extraction removes scripts, styles,
`noscript`, templates, SVG, iframes and hidden markup. Prompt-injection patterns are
checked against the raw bounded source before stripping. The response retains canonical
requested/final URLs, redirects, content type, title, extracted text, SHA-256 digest,
robots status and extraction version, but never returns raw bytes or the resolved IP.
Every result is explicitly `evidence_admitted=false`.

PDF responses fail with `page_binary_scan_required`. No binary text extraction is
reachable until the reusable malware-scan and sandbox-parser boundary exists. This
adapter has no route to a model, `evidence`/`claims` tables or the report composer.

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
evidence or a model except through the file-safety boundary below.
Source locators reject embedded password/token/API-key material.

## File-safety boundary

`mandate_worker.providers.file_safety` is the only route from a quarantined filing
binary to text. `FileSafetyPipeline.process` enforces one mandatory sequence:

1. **Quarantine integrity** — the submitted bytes must be non-empty, at most 25 MiB and
   an exact size plus constant-time SHA-256 match for the still-quarantined reference.
2. **Malware scan** — the outer binary, and every ZIP member individually, must return a
   clean verdict whose reported digest matches the submitted bytes. `DEMO_MODE=1` uses
   the SHA-256-allowlisted fixture scanner (unknown binaries fail closed); live mode may
   explicitly select `PROVIDER_MALWARE_SCANNER=clamd_unix`, a bounded local ClamAV
   `clamd` INSTREAM Unix-socket transport configured via `CLAMD_SOCKET_PATH`. Scanner
   errors, timeouts and malformed replies are failures, never clean results.
3. **Archive limits** — ZIPs are bounded to 50 members, 25 MiB per member, 100 MiB total
   uncompressed and a 100× compression ratio, with stored/deflated compression only.
   Traversal, absolute and Windows-style paths, case-folded duplicate names, symlinks,
   encrypted members, nested archives and non-PDF members are rejected, as are PDF/ZIP
   polyglots and media-type mismatches.
4. **Sandbox parse** — parsing requires a `networkless_readonly_v1` attestation
   (network disabled, read-only filesystem, active content removed) plus matching
   source and text digests. `DEMO_MODE=1` replays the pinned parser fixture; **no live
   parser binding is allowlisted**, so live PDF parsing stays fail-closed — even when
   ClamAV is available — until the parser runs in an isolated networkless, read-only,
   resource-limited service and returns the required attestation.

Results carry only audit-safe metadata and parsed text marked `untrusted=true` and
`evidence_admitted=false`. Failures raise stable `FileSafetyError` codes that never
contain document bytes, raw scanner output or source paths. This module has no route to
a model, the composer or the `evidence`/`claims` tables; evidence admission remains a
later, separate step.

## ModelGateway boundary

`mandate_worker.providers.ModelGateway` is the sole model-call boundary. A versioned
`ModelTaskRoute` fixes the model id, prompt-bundle version, task payload allowlist,
provider allowlist, input/output token ceilings and per-call cost ceiling. The caller
also supplies the remaining per-job model budget; responses that exceed any limit fail
before structured output is returned.

Provider payloads contain only task-allowlisted public identifiers and admitted content.
Unknown top-level fields and recursively nested account identity, firm, billing, payment,
letterhead, confidential-matter, credential and secret keys are rejected. Raw fetched
pages, parsed-but-unadmitted text and quarantined binaries have no direct gateway path.

Every provider request carries `zdr=true` plus an explicit provider allowlist. A response
from a provider outside that allowlist raises `NoApprovedCapacity`; there is no silent
fallback. Output is validated against the caller's Pydantic schema, with exactly one
bounded repair retry. Audit output is a typed `AgentRunRecord` containing ids, task,
model/provider, prompt version, token counts, cost, latency, ZDR status, repair status,
success and a stable error code—never prompts, payloads or provider output.

`DEMO_MODE=1` selects the SHA-256-pinned deterministic fixture router and records zero
spend. Live `openrouter` selection requires an injected transport and reviewed route map;
missing routes, missing transport, fixture selection outside demo mode and unknown
bindings fail closed. Production route/provider selection and credentials remain blocked
on B3. Persistence of `AgentRunRecord` moves to the next migration slice.

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
