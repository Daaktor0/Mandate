# BUILD-CHECKLIST — Dependency-Safe Implementation Plan

**Status header (update after every tested phase):**

> **Current phase:** 0 — Engineering foundation (7/11 tasks complete) · **Last gate passed:** — · **Updated:** 2026-07-13

**Sources:** product-specification doc 13 (authoritative phase order and gates); master prompt ("follow the build roadmap exactly; use vertical slices; update the checklist after every tested phase")
**Related:** [REQUIREMENTS-TRACEABILITY.md](REQUIREMENTS-TRACEABILITY.md), [TEST-PLAN.md](TEST-PLAN.md), [ARCHITECTURE-DECISIONS.md](ARCHITECTURE-DECISIONS.md) (blockers B1–B14)

Ordering principle (doc 13): **correct entity → reliable evidence → useful questions → trusted Mandate Brief → safe billing.** Do not begin with a polished dashboard or theatrical multi-agent framework.

---

## Phase 0 — Engineering foundation

- [x] Monorepo scaffold per SYSTEM-SPEC §3 (apps/web, services/worker, packages/shared-schemas, supabase, infra, fixtures)
- [x] Toolchain pinned (SYSTEM-SPEC §4); lockfiles committed; lint/format/typecheck configured (web + worker)
- [x] Shared-schemas package: first schemas (EntityCandidate, Evidence, Claim, JobMessage) + codegen (Pydantic + zod) + drift check in CI
- [x] Supabase local stack + first migration: `users_profile`, `report_requests`, RLS default-deny pattern, `is_admin()` helper
- [x] Worker skeleton: FastAPI `/health`, job-loop shell, `QueueAdapter` (pgmq + memory), structured logs with `trace_id`
- [x] **Spike:** pgmq visibility-timeout/lease-extension behaviour (validates AS-02; [result](spikes/AS-02-pgmq-lease-extension.md))
- [x] Docker images (worker, renderer) + local Compose; renderer sandbox profile
- [ ] CI pipeline stages 1–5 (TEST-PLAN §11) incl. secret scan (SEC-10) and dependency/container scans (SEC-12)
- [ ] Fixtures directory + demo-mode wiring switch (`DEMO_MODE=1`, ADR-014)
- [ ] Threat model reviewed against scaffold (SECURITY-THREAT-MODEL); no deviations
- [ ] Traceability report generator (CI stage 7) reading REQUIREMENTS-TRACEABILITY.md

**Gate G0:** reproducible staging-shaped deployment from Compose; zero secrets in repo/images; baseline tests green in CI.

## Phase 1 — Entity-resolution proof of concept

- [ ] Intake API + validation (INTAKE-01..06): URL safety (SafeFetcher policy, ADR-011), confidential ack, CIN optional
- [ ] SafeFetcher module + full SSRF unit table (SEC-03 foundations)
- [ ] Legal-page crawler (discovery order, AGENT-PROMPT §3 step 1) + extraction (CIN/GSTIN/legal-suffix/office patterns)
- [ ] `CompanyDataProvider` interface + fixture impl; real name-to-CIN adapter behind flag (Blocker B5)
- [ ] Candidate generation + deterministic confidence scoring (doc 05 weights) + labels
- [ ] `entities`, `entity_candidates` migrations; light-queue resolution task; states `draft → resolving_entity → awaiting_entity_confirmation`
- [ ] Minimal confirmation UI: candidate cards (evidence snippets, confidence labels), confirm / none-of-these / refine / related-entity scope (ENTITY-03/04/07)
- [ ] ER-01..11 fixture suite green
- [ ] **Live test:** ≥30 varied companies (needs B5 trial credentials on staging)

**Gate G1:** ambiguous cases ask instead of guessing; no paid research reachable before confirmation. *(Slices E2E-01 partially: website → candidate.)*

## Phase 2 — Evidence pipeline

- [ ] `SearchProvider` + `PageFetcher` adapters (fixture + one real behind flag; benchmark harness for B4)
- [ ] ModelGateway (ADR-005): routing config, ZDR/allowlist params, payload allowlist, schema validation + repair retry, `agent_runs` logging, cost caps (needs B3 for live; fixture ModelRouter for CI)
- [ ] `evidence`, `claims`, `job_checkpoints`, `agent_runs`, `provider_cost_events` migrations
- [ ] Source-tier classification + evidence-object capture (doc 06 fields)
- [ ] Research stages 2–7 (business, industry, competitors, corporate, regulatory, public-risk) with typed `AgentFinding` outputs, claim drafting, freshness windows (REPORT-08/09)
- [ ] Prompt architecture: untrusted envelopes, injection rules, suspicion flags (SEC-04 foundations)
- [ ] Budgets: per-job caps + per-stage slices + stopping rules (RUN-07)
- [ ] Checkpointing + resume (kill-and-resume test)
- [ ] Contradiction/coverage verifier (stage 8)
- [ ] Golden fixtures GC-01..15 authored (inputs + expectations)

**Gate G2:** an evidence bundle is reviewable without any prose; every claim carries metadata (type, evidence ids, confidence, freshness). *(Slice E2E-02: confirmed entity → evidence.)*

## Phase 3 — Clarification and questions

- [ ] Preliminary-research light task + clarification planner (mandatory client role with reason; optional overlay; foreign-investment question) (RESEARCH-01..07)
- [ ] Clarification API + UI; mandatory-question enforcement; confidential-content screening of free text
- [ ] Transaction-preparation analyst (stage 9): matters for attention, gaps, `KickoffQuestion` set with role adaptation
- [ ] Question quality rubric harness (doc 12 dimensions) over golden cases
- [ ] **Lawyer review round 1:** questions useful; no confidential narrative requested

**Gate G3:** lawyer-reviewed questions rated useful; no clarification solicits confidential information. *(Slice E2E-03: evidence → questions.)*

## Phase 4 — Mandate Brief composer and editor

- [ ] `BriefDocument` schema (ADR-007) + composer (stage 10) using approved claims/inferences/conflicts/gaps only
- [ ] Length controller (ADR-009): class selection, section budgets, deterministic trim, measurement loop
- [ ] Renderer: WeasyPrint print stylesheet, pinned fonts, page measurement, source annex outside cap
- [ ] Final verifier (stage 11) + full QG check set (AGENT-PROMPT §10) + known-bad fixture tests
- [ ] `reports`, `report_versions` migrations; immutable v0 trigger (EDIT-02)
- [ ] Editor UI on BriefDocument; save-as-version; revert; unsupported-user-text warnings (EDIT-01/03/04/05)
- [ ] Letterhead: upload/scan/rasterise/stamp/preview/expiry (EDIT-06..09) + renderer sandbox (SEC-05 foundations)
- [ ] Version/render/download APIs incl. signed links (HISTORY-03)

**Gate G4:** no clipping at any length class; a Mandate Brief is reproducible from stored inputs; letterhead absent from all model calls and logs. *(Slices E2E-04, E2E-05, E2E-09 without payments.)*

## Phase 5 — Queue, accounts and notifications

- [ ] Google/Microsoft OAuth via Supabase (B1, B2); first-login profile; terms/privacy acceptance
- [ ] Dashboard: statuses (doc 03 list), recent briefs, active jobs (HISTORY-01/02)
- [ ] Heavy queue end-to-end: outbox relay, lease/heartbeat, retry_wait backoff, DLQ, cancellation
- [ ] Truthful progress endpoint + UI (7 stages, ADR-012)
- [ ] Email notifications (B6) + `notification_log` idempotency
- [ ] Admin job view: stages, retries, provider errors, costs; retry/cancel actions
- [ ] Vercel project setup: repo integration, preview/production environments, env vars, wait-for-CI check (B14; ADR-016; DEPLOYMENT §4)
- [ ] Hostinger provisioning + worker staging deploy (B9; DEPLOYMENT §3–4)
- [ ] Two-worker concurrency test (NFR-10); worker-restart recovery test (AT-NFR-01)

**Gate G5:** worker restart recovers mid-job; tenant isolation verified (SEC-01 matrix); concurrency bounded. *(Slice E2E-06: account → queued report.)*

## Phase 6 — Payments

- [ ] Razorpay orders (server-fixed pricing config; FOUNDER_CONFIRM B13), checkout, provisional confirm (B7 test mode)
- [ ] Webhook handler: HMAC, `webhook_events`, idempotent grants (PAY-02/03/09)
- [ ] Entitlement ledger + invariants + reserve+enqueue transaction (ADR-010); balance view; AUTH-04 display
- [ ] Consume/release/restore side effects wired to job outcomes (PAY-05/06/08; RUN-09); one-click refund offer (PAY-07)
- [ ] Trial claiming: phone OTP (B8), abuse controls, cohort cap (AUTH-06, ADR-013)
- [ ] Pack validity/expiry events (AS-13); regeneration-as-new-request (EDIT-10)
- [ ] Reconciliation job + admin reconciliation view (PAY-10)
- [ ] SEC-06/07/08 suites green

**Gate G6:** webhook replay safe; double-consume impossible under race tests; failed jobs restore; refunds reconcile. *(Slices E2E-07, E2E-08.)*

## Phase 7 — Quality and private beta

- [ ] Automated gates enforced as completion condition in production config
- [ ] Issue workflow: report → investigate → root cause → restore/correct (ISSUE-01..04) + admin queue
- [ ] Golden suite green in demo mode (CI) and against live providers (staging benchmark; B3/B4 resolved)
- [ ] Cost dashboard + daily spend ceiling verified; 30-brief cost measurement (feeds pricing, R-02)
- [ ] Consented edit collection: `training_consent`, opt-in UI, anonymised capture (doc 12; opt-in only)
- [ ] Retention/deletion jobs live + verified (SEC-14); account deletion (AUTH-05)
- [ ] Full security gate SEC-01..15 green; WCAG AA audit (NFR-06)
- [ ] ≥30 lawyer-reviewed briefs pass rubric targets (doc 12; charter launch gate)
- [ ] Incident/refund runbooks rehearsed

**Paid-launch gate G7:** charter §12 criteria met; unit economics measured and stable; terms/privacy reviewed (B10) and GST treatment resolved (B11); incident and refund procedures tested.

---

## Vertical slices → phase map (doc 13)

| Slice | Phase(s) |
|---|---|
| E2E-01 website → candidate | 1 |
| E2E-02 confirmed entity → evidence | 2 |
| E2E-03 evidence → questions | 3 |
| E2E-04 evidence + answers → Brief JSON | 4 |
| E2E-05 Brief JSON → PDF | 4 |
| E2E-06 account → queued report | 5 |
| E2E-07 payment → entitlement → consume | 6 |
| E2E-08 failure → restore/refund | 6 |
| E2E-09 edit → version → letterhead PDF | 4–5 |
| E2E-10 issue → investigation → correction | 7 |

## Do not build first (doc 13 guardrails)

Workspaces; collaboration; unlimited group research; confidential uploads; small model (doc 14 is post-MVP); mobile app; visual agent canvas; all-country registries; direct MCA document purchase; deep analytics.

## Founder-parallel track (non-engineering, from doc 13)

Interview 10–15 transaction lawyers; show a manual Mandate Brief; test page-length preference and ₹999 willingness; record actual kickoff questions; capture procurement/security objections. Feeds Phases 3 and 7 gates.
