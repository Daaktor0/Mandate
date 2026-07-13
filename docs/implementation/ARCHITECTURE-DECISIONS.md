# ARCHITECTURE-DECISIONS — ADRs, Assumptions, Risks and Blockers

**Status:** Specified
**Sources:** product-specification docs 08, 09, 13, 15, 16; Fable 5 master prompt
**Related:** [SYSTEM-SPEC.md](SYSTEM-SPEC.md), [DEPLOYMENT-SPEC.md](DEPLOYMENT-SPEC.md)

ADR statuses: **Accepted** (binding for MVP), **Proposed** (needs founder/empirical input). Product-level decisions already frozen in the spec pack (Supabase, Hostinger worker, OpenRouter, Razorpay, queue-driven code-based workflow, pricing model) are treated as constraints, not re-decided here.

---

## Part A — Architecture Decision Records

### ADR-001 — Single monorepo with pnpm workspaces (web) and uv (worker)

**Status:** Accepted.
**Context:** One small team; web, worker and shared contracts must move in lockstep; requirement IDs must be traceable across tickets/tests/PRs (doc 02).
**Decision:** One repository containing `apps/web`, `services/worker`, `packages/shared-schemas`, `supabase/`, `infra/`, `fixtures/` (layout in SYSTEM-SPEC §3). pnpm workspaces for JS; uv-managed virtualenv for Python.
**Consequences:** Single CI pipeline and single traceability matrix; cross-language schema generation is possible from one source; repo grows large but remains navigable.

### ADR-002 — Supabase Queues (pgmq) as MVP queue, behind a `QueueAdapter`

**Status:** Accepted (mandated by doc 08; adapter shape is the decision).
**Context:** Durable delivery and retries with minimal moving parts; later SQS migration.
**Decision:** One logical job queue on pgmq. All queue operations go through `QueueAdapter` (`send`, `lease`, `extend_lease`, `archive`, `dead_letter`) with three implementations: `PgmqQueueAdapter` (MVP), `SqsQueueAdapter` (migration), `MemoryQueueAdapter` (tests/demo). Enqueue is performed via a transactional **outbox** table drained by a relay, never directly inside a web request transaction that could partially fail (see ADR-010, QUEUE-AND-JOB-SPEC §4).
**Consequences:** Exactly-once *effects* are achieved by idempotent consumers + ledger idempotency keys, not by the queue; SQS migration touches one module.

### ADR-003 — Explicit typed orchestration in the worker; no LangGraph in MVP

**Status:** Accepted.
**Context:** Doc 08 permits "explicit orchestration or LangGraph". The pipeline is a fixed DAG of bounded stages with deterministic checkpoints (doc 04); auditability and checkpoint resume are hard requirements.
**Decision:** A hand-written pipeline runner: each stage is a pure-ish `Stage[TIn, TOut]` with Pydantic input/output, its own budget slice, and a checkpoint write on completion. No framework-managed hidden state.
**Consequences:** More explicit code, less magic; stage graph changes are code changes (acceptable — the graph is a product decision); trivially resumable from `job_checkpoints`.

### ADR-004 — Contract-first shared schemas (JSON Schema → Pydantic + zod/TypeScript)

**Status:** Accepted.
**Context:** The same objects (entity candidate, evidence, claim, research plan, finding, contradiction, kickoff question, quality gate, brief document) cross the web/worker boundary; templates/AGENT-OUTPUT-SCHEMAS.md demands strict validation of every model output.
**Decision:** JSON Schema files in `packages/shared-schemas/schemas/` are the source of truth; codegen produces Pydantic v2 models and zod schemas. Every model output and every queue message is validated against these before use. Schemas carry a `schemaVersion`.
**Consequences:** One place to evolve contracts; codegen step in CI; breaking schema changes are visible in review.

### ADR-005 — OpenRouter behind an internal ZDR-enforcing model gateway

**Status:** Accepted (mandated; gateway behaviour is the decision).
**Context:** Doc 10 requires per-request ZDR, provider allowlist, identity exclusion, fail-safe behaviour; NFR-05/09 require cost and prompt-version audit.
**Decision:** A single `ModelGateway.complete(task, payload, budget)` entry point. It (a) resolves task→model from a versioned routing config (AGENT-PROMPT-SPEC §9); (b) sets OpenRouter ZDR + provider allowlist parameters on every call; (c) validates structured output against the task's schema with one repair retry; (d) enforces per-call and per-job token/cost caps; (e) writes an `agent_runs` row (model, prompt version, tokens, cost, latency, ZDR flag, result); (f) refuses to send any field classified account/billing/branding (SECURITY-THREAT-MODEL §3) — enforced by an explicit payload allowlist, not redaction after the fact; (g) raises `NoApprovedCapacity` (job → retry_wait) rather than falling back to a non-allowlisted provider.
**Consequences:** All model traffic is auditable and privacy-bounded; a gateway bug is a single point of failure, so it gets the densest unit tests (TEST-PLAN §3).

### ADR-006 — Provider adapters with fixture implementations and feature flags

**Status:** Accepted.
**Context:** No vendor credentials exist yet (Blockers B1–B7); master prompt requires adapters/mocks until credentials exist, feature-flagged paid providers and a zero-spend local demo.
**Decision:** Every external capability sits behind an interface (SYSTEM-SPEC C8). Each has: one real implementation (added when credentials exist), one **fixture** implementation replaying recorded/synthetic responses from `fixtures/demo/`, and a config flag (`PROVIDER_SEARCH=brave|tavily|exa|fixture`, etc.). `DEMO_MODE=1` forces all-fixture wiring.
**Consequences:** The full pipeline is developable and testable today; provider selection (doc 15) becomes a config + benchmark exercise on the golden set, not a refactor.

### ADR-007 — Mandate Brief is versioned document JSON; rendering is derived

**Status:** Accepted.
**Context:** EDIT-02/03/05 (immutable system draft, versioned edits, revert); REPORT-01..03 (length control); PDF re-render must not rerun research (doc 03 errors).
**Decision:** The canonical Mandate Brief is a `BriefDocument` JSON (sections A–G + header + source annex + per-block claim references — schema in AGENT-PROMPT-SPEC §7). `report_versions.document_json` stores each version; version 0 is the system draft and is never mutated. HTML and PDF are pure functions of (document JSON, render options, optional letterhead). Edits produce new versions; user-added blocks carry `origin: "user"` so unsupported-text warnings (EDIT-04) and AI/user separation (doc 01 §7) are structural.
**Consequences:** Reverts and issue reports pin exact versions; renderer bugs never corrupt content; diffing versions is JSON diffing.

### ADR-008 — Deterministic HTML→PDF via WeasyPrint; letterhead overlay via pypdf

**Status:** Accepted.
**Context:** Page-count is a product rule (1–4 pages), so pagination must be measurable and deterministic; letterhead is render-only and must never reach models (EDIT-07); active PDF content must be stripped (doc 10).
**Decision:** WeasyPrint renders the brief HTML with a fixed print stylesheet (no JS execution at all), giving deterministic page counts the length controller can trust. Letterhead: uploaded PDF/PNG/JPG is scanned, rasterised/sanitised, then stamped as background/header with pypdf in a sandboxed render step; margins and continuation-page behaviour are render options. Playwright is **not** used for PDF (it stays extraction-only), keeping the render path JS-free.
**Consequences:** No headless-browser rendering variance; CSS print debugging is the cost; letterhead never enters any prompt or log by construction.

### ADR-009 — Length controller: budgeted composition + deterministic post-measure loop

**Status:** Accepted.
**Context:** REPORT-01/02: default two pages, automatic 1–4; "do not pad"; annex excluded from cap.
**Decision:** Two cooperating mechanisms (detail in AGENT-PROMPT-SPEC §8): (1) the supervisor computes a **target length class** (1/2/3/4 pages) from complexity signals (multi-entity, listed, regulated sector, cross-border, evidence volume, sparse-data flag) and gives the composer per-section word budgets; (2) after render, the actual page count is measured; if over target, a deterministic trim protocol removes lowest-priority content (never questions, never uncertainty labels, never matters-for-attention entries above the floor) and re-renders; if under target with no more approved content, the shorter brief ships (no padding). Hard fail if >4 pages after two trim passes.
**Consequences:** Page cap is enforced by measurement, not model promises; trim priorities are explicit and testable.

### ADR-010 — Append-only entitlement ledger + single reservation transaction + outbox

**Status:** Accepted.
**Context:** PAY-03..10, doc 09 entitlement transaction, doc 11 accounting; races and double-spend are pre-launch test items.
**Decision:** `entitlement_ledger` is insert-only; balances are derived (`available = grants − reservations − consumes + releases/restores − expiries`, materialised in a view). The reserve step is one serializable transaction: lock user balance row, reject if an active generation exists for the request, insert `reserve` event, insert `report_jobs` row, insert outbox row; commit. Consume/release/restore events reference the reserve event and carry idempotency keys `(job_id, event_type)`. Invariants (ERD §12) are enforced with DB constraints + a reconciliation job.
**Consequences:** Ledger is auditable (PAY-10) and replay-safe; balance reads are slightly heavier (a view), which is acceptable at MVP volume.

### ADR-011 — SSRF-safe fetching is a dedicated module with pinned-IP connections

**Status:** Accepted.
**Context:** INTAKE-03; doc 10 retrieval threats (private/reserved IPs, metadata endpoints, redirect + DNS-rebinding games); doc 05 acceptance test "private-IP redirects".
**Decision:** All outbound page fetches go through `SafeFetcher`: HTTP/HTTPS only; resolve DNS, reject private/reserved/link-local/metadata ranges, then **connect to the vetted IP** (pinned) with SNI/Host set, so a re-resolving DNS name cannot swap targets mid-request; every redirect re-runs the full check; max 5 redirects; per-fetch size/time caps; content-type allowlist; robots/ToS-respecting behaviour per doc 06. Playwright traffic is forced through the same policy via request interception, with a browser-context proxy denylist as defence in depth.
**Consequences:** One choke point to test hard (SEC tests); slightly more complex connection code than plain httpx.

### ADR-012 — Truthful progress = checkpoint-driven stage events only

**Status:** Accepted.
**Context:** RUN-02; doc 03 lists exactly seven user-visible stages; no fake percentages; no chain-of-thought exposure.
**Decision:** The worker emits a stage event only when a pipeline stage actually completes a checkpoint; the web app maps internal stages → the seven doc-03 labels (mapping table in QUEUE-AND-JOB-SPEC §7) and renders them as a checklist with timestamps. No percentage bars anywhere.
**Consequences:** Progress can appear "slow but honest" on long stages; acceptable and explicitly desired by the spec.

### ADR-013 — Trial abuse: phone OTP + risk signals at trial grant, not at signup

**Status:** Accepted.
**Context:** AUTH-06, doc 11 trial controls (one free Mandate Brief for first 100 eligible verified users), doc 03 (phone verification for trial).
**Decision:** Signup requires only OAuth. Claiming the trial entitlement requires: verified phone (OTP), non-disposable email domain, one trial per (person, phone, device fingerprint, risk cluster), IP-velocity checks, CAPTCHA when risky, manual blocklist. Trial grant is a ledger event like any purchase. No card requirement unless abuse becomes unmanageable.
**Consequences:** Friction lands only on the free path; risk signals are auditable in admin (ADMIN-01).

### ADR-014 — Fixture-based demo mode is a first-class, CI-tested configuration

**Status:** Accepted.
**Context:** Master prompt requires a local demo without API spending; golden cases need deterministic inputs.
**Decision:** `DEMO_MODE=1` wires all adapters to fixtures, seeds a demo user/entitlements, and can run every E2E slice offline. Golden-case fixtures (GC-*) double as the demo corpus. CI runs the demo E2E suite on every PR.
**Consequences:** The demo can drift from live-provider reality; mitigated by a separate staging benchmark task (BUILD-CHECKLIST Phase 2).

### ADR-015 — Email, phone OTP and observability kept adapter-thin

**Status:** Accepted.
**Context:** RUN-10 (email), AUTH-06 (phone), NFR-04/05; vendor choices are blocked on accounts (B6, B8).
**Decision:** `EmailProvider` (console sink in dev; Resend or SES chosen at Phase 5 — see B6), Supabase Auth phone OTP with SMS provider configured at Phase 6 (B8), structured JSON logs with `trace_id` on every log line, and a FastAPI `/health` + `/metrics-lite` endpoint on the worker. No heavy APM in MVP.
**Consequences:** Vendor swaps stay trivial; some observability is manual (admin queries) at MVP.

### ADR-016 — Web hosting for staging/production: Vercel

**Status:** Accepted (founder decision, 2026-07-13).
**Context:** Doc 08 fixes Supabase + Hostinger worker but not where Next.js is served. The frontend needs Node SSR, low ops burden and portability. Options considered: (a) Vercel; (b) Next.js standalone on the same Hostinger KVM 2 behind Caddy; (c) a separate Hostinger instance.
**Decision:** Host the Next.js app on Vercel (staging = preview/branch deployments, production = the production deployment), "for now" — revisit at AWS migration or if Vercel constraints bite.
**Consequences:** Fastest path with zero web-ops burden and the KVM 2's 8 GB stays dedicated to the worker/renderer. Adds a vendor: Vercel joins the environment/secret inventory, key-rotation runbook and (as a data subprocessor serving the app) the pre-launch privacy review (B10). Long-running work must never move into web routes — route handlers stay short (NFR-07); generation remains on the queue/worker. Razorpay webhooks terminate at a Vercel route backed by durable `webhook_events` recording, which fits the existing design. Portability guard: no Vercel-proprietary APIs (KV/queues/cron/blob) — Supabase and the worker keep those roles, so the app remains deployable as a standalone Node container if we leave.

---

## Part B — Adopted assumptions

Assumptions inherited from doc 16 (founder decisions/defaults) are not repeated; these are **new implementation-level assumptions** this spec set adopts. Each is safe to reverse before its phase begins.

| ID | Assumption | Basis / impact if wrong |
|---|---|---|
| AS-01 | Version lines in SYSTEM-SPEC §4 are acceptable and current-stable at build time | Re-pin at Phase 0; no design impact |
| AS-02 | Supabase Queues visibility-timeout semantics are sufficient for ≤30-minute jobs with lease extension | **Verified conditionally, 2026-07-13** ([spike](spikes/AS-02-pgmq-lease-extension.md)): every heartbeat must be a short committed/autocommit operation; fallback remains a `pg`-native lease table behind the same adapter |
| AS-03 | WeasyPrint print output is deterministic enough for page-count gating across container rebuilds | Pin fonts in the image; golden render tests catch drift |
| AS-04 | The seven doc-03 progress stages map cleanly onto internal pipeline stages | Mapping table maintained in QUEUE-AND-JOB-SPEC §7 |
| AS-05 | "Two low-concurrency jobs" (doc 08) = worker concurrency 2, global; enforced via queue lease count | Tunable config |
| AS-06 | `mvp-standard` budget profile starts from the illustrative values in AGENT-OUTPUT-SCHEMAS (45 searches / 100 pages / 4 frontier calls / 1200 s) plus token caps in AGENT-PROMPT-SPEC §10; recalibrated after 30 measured briefs | Doc 11 requires empirical validation anyway |
| AS-07 | English-only UI and Mandate Briefs at MVP | No spec mention of other languages |
| AS-08 | INR-only pricing/Razorpay at MVP; cross-border *targets'* counterparties don't imply foreign-currency billing | Doc 11 pricing is INR |
| AS-09 | Admin panel is an RBAC-gated area of the same Next.js app, not a separate deployment | Smaller surface; separate admin role per doc 10 |
| AS-10 | "Up to two material related entities" render as labelled subsections within the same BriefDocument, not separate documents | ENTITY-07/08 satisfied by labelling |
| AS-11 | Phone verification uses Supabase Auth OTP with a pluggable SMS provider | B8 |
| AS-12 | Source annex default presentation: appended to the PDF after the main brief (outside page cap), with a download-time toggle | Doc 16 defers the default; toggle keeps it reversible |
| AS-13 | Report entitlement validity (90/120 days) is enforced at reserve time against `expires_at` on grant events | Doc 11 suggested validity |
| AS-14 | Trial cohort cap ("first 100 eligible users") enforced by a counted config gate at trial-grant time | Doc 11 |

## Part C — Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | Entity resolution accuracy below trust bar on real Indian company data (name variants, stale registries) | Medium | Critical (wrong entity = automatic failure) | Phase 1 gate: 30-company varied test set; confidence labels + mandatory confirmation; CIN prompt on ambiguity; golden cases GC-* |
| R-02 | Unit economics: real cost per brief exceeds price envelope (doc 11 warns ₹150/brief is unsustainable) | Medium | High | Per-report cost attribution (NFR-05) from Phase 2; measure 30 briefs before pricing launch; model routing + stopping rules |
| R-03 | Hostinger KVM 2 (2 vCPU/8 GB) too small for Playwright + WeasyPrint + 2 concurrent jobs | Medium | Medium | Resource limits per Compose service; bounded browser use; measured in Phase 5 gate; AWS path ready |
| R-04 | ZDR-eligible OpenRouter capacity unavailable for a needed model tier at run time | Medium | Medium | Gateway fail-safe → retry_wait, never silent fallback; allowlist includes ≥2 providers per tier |
| R-05 | Litigation/public-risk sources yield common-name false positives | High | High (trust) | Doc 06 matching rules (strong identifiers only); precision-over-recall; GC-12 adverse false-positive case gates release |
| R-06 | Free-tier provider limits break generation mid-job at prototype budget (~₹1,000/month) | Medium | Medium | Budgets + checkpoint resume; retry_wait on provider quota errors; low-volume testing plan |
| R-07 | Prompt-injection or SSRF bypass via crafted target website | Medium | Critical | ADR-011 pinned-IP fetcher; injection defence in every agent prompt + suspicion flags on evidence; SEC test suite is a launch gate |
| R-08 | Page-length gate flaky due to font/render drift | Low | Medium | ADR-008 deterministic renderer, pinned fonts, golden render tests |
| R-09 | Webhook/entitlement race conditions double-consume or double-grant | Low | High | ADR-010 serializable reserve, idempotency keys, replay tests SEC-07, reconciliation job |
| R-10 | Scope creep into diligence/legal-advice territory in composed text | Medium | High (legal) | Composer constraints + final-verifier prohibited-language checks (AGENT-PROMPT §8); disclaimer mandatory |
| R-11 | Supabase Queues semantics surprise (AS-02 wrong) | Low | Medium | Phase 0 spike; adapter swap path |
| R-12 | Solo-founder bus factor on ops (Hostinger, keys, incidents) | High | Medium | DEPLOYMENT-SPEC runbooks; documented key rotation; snapshots |

## Part D — Genuine blockers

Items that require founder action or external accounts. **None blocks Phases 0–4**, because every external dependency has a fixture adapter (ADR-006). Each lists the phase by which it must be resolved.

| ID | Blocker | Blocks | Needed by | Mitigation until resolved |
|---|---|---|---|---|
| B1 | Google + Microsoft OAuth client credentials (Cloud/Entra apps) | Real login | Phase 5 | Supabase local auth + seeded test users |
| B2 | Supabase staging/production projects | Staging deploys | Phase 5 | Supabase CLI local stack |
| B3 | OpenRouter API key + confirmation of ZDR-eligible providers for each model tier | Real model calls | Phase 2 (staging benchmark) | Fixture ModelRouter; recorded completions |
| B4 | Search-provider selection + key (Brave vs Tavily vs Exa; doc 15 says benchmark one primary) | Real search | Phase 2 (benchmark) | Fixture SearchProvider; benchmark harness ships in Phase 2 |
| B5 | Company-data provider trial (Attestr name-to-CIN or equivalent; doc 15 shortlist) | Real CIN lookup | Phase 1 (staging accuracy test) | Fixture CompanyDataProvider with synthetic + hand-collected public records |
| B6 | Transactional email account + sending domain (Resend/SES) | Real notifications | Phase 5 | Console/log email sink |
| B7 | Razorpay account, keys, webhook secret | Real payments | Phase 6 | Razorpay test mode first; fixture webhook events for CI |
| B8 | SMS/OTP provider for phone verification | Trial eligibility | Phase 6 | Feature-flag trial claiming off |
| B9 | Hostinger KVM 2 SSH access provisioned for deployment | Staging worker | Phase 5 | Local Compose is bit-identical |
| B10 | Terms of service + privacy policy legal review (doc 13 paid-launch gate) | Paid launch | Phase 7 gate | Draft from doc 10 boundaries; flag for counsel |
| B11 | GST/tax presentation of pricing (doc 11: "requires accounting review") | Paid launch | Phase 7 gate | Display "excl. taxes" placeholder in staging only |
| B12 | Litigation/legal-database licensing decision (doc 15: do not assume automation rights) | Public-risk depth beyond official portals | Post-MVP | MVP uses official court/tribunal/regulator sources + credible legal news only, via adapter |
| B13 | Founder checklist confirmations (doc 16): pack pricing/expiry, 24 h letterhead deletion, related-entity cap, optional transaction type, mandatory client role, phone-verified trial, opt-in edit training | Final copy + config values | Phase 6 | Spec defaults from doc 16 wired as config, marked `FOUNDER_CONFIRM` |
| B14 | Vercel account + project linked to the repo (ADR-016); Pro plan before paid launch (commercial-use terms) | Hosted web (staging previews, production) | Phase 5 | Local `next dev` and demo mode need no hosting |

## Part E — Decisions explicitly deferred (unchanged from doc 16)

Final visual design; source-annex default (AS-12 keeps it a toggle); saved letterheads; subscriptions; workspaces; enterprise SSO; foreign primary targets; paid MCA documents; legal-database vendor; premium human review; mobile app; Closing Room integration; small-model/GPU choice; collaboration; group pricing.
