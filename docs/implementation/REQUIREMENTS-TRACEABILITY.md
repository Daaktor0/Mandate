# REQUIREMENTS-TRACEABILITY — Mandate MVP

**Status:** Phase 2 in progress (5/13 tasks complete); Phase 1 live benchmark remains blocked at 8/9; `NFR-03` is `Verified`; `INTAKE-01`, `INTAKE-03`, `INTAKE-05`, `ENTITY-01`, `ENTITY-02`, `ENTITY-03`, `ENTITY-04`, `ENTITY-05`, `ENTITY-07` and `RUN-05` are `Implemented`; `NFR-01`, `NFR-02`, `NFR-04`, `NFR-05`, `NFR-09`, `INTAKE-02`, `INTAKE-04`, `INTAKE-06`, `RUN-06` and `RUN-07` are `In progress`; all other requirements remain `Specified`
**Sources:** product-specification doc 02 (requirement IDs are normative and must be preserved in tickets, tests and PRs)
**Related:** [TEST-PLAN.md](TEST-PLAN.md) (test IDs), [SYSTEM-SPEC.md](SYSTEM-SPEC.md) (component codes C1–C15), [BUILD-CHECKLIST.md](BUILD-CHECKLIST.md) (phases)

Columns: **Component** uses SYSTEM-SPEC §2 codes; **DB / API surface** cites ERD tables and API-SPEC endpoints; **Acceptance tests** cite TEST-PLAN IDs (`AT-<REQ>` is the requirement's dedicated acceptance test; extra IDs add coverage); **Phase** is the build phase where the requirement is implemented; **Status** uses the README legend. CI enforces this matrix (TEST-PLAN §11 stage 7).

## Authentication and account

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| AUTH-01 | Google OAuth login | C3, C1 | Supabase Auth; `users_profile` | AT-AUTH-01, E2E-06 | 5 | Specified |
| AUTH-02 | Microsoft/Outlook OAuth login | C3, C1 | Supabase Auth; `users_profile` | AT-AUTH-02, E2E-06 | 5 | Specified |
| AUTH-03 | Individual-user accounts | C3, C4 | RLS user scoping; no org tables | AT-AUTH-03, SEC-01 | 5 | Specified |
| AUTH-04 | Show purchased/reserved/consumed/restored/expired entitlements | C1, C2 | `entitlement_ledger` view; `GET /api/me` | AT-AUTH-04 | 6 | Specified |
| AUTH-05 | Account deletion with billing/security retention | C2, C4 | `DELETE /api/account`; tombstones (ERD §6) | AT-AUTH-05, SEC-14 | 7 | Specified |
| AUTH-06 | Trial eligibility: email, verified phone, device, abuse signals | C2, C3 | `users_profile.trial_*`; `/api/me/phone/*`, `/api/me/trial-claim` | AT-AUTH-06, SEC-08 | 6 | Specified |

## Intake

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| INTAKE-01 | Require only website URL or legal name | C1, C2 | generated create-request schemas; `POST /api/report-requests`; tenant-scoped `create_report_request` RPC | AT-INTAKE-01 (route + database idempotency), E2E-01 | 1 | Implemented |
| INTAKE-02 | Website helper text (entity-confirmation promise) | C1 | authoritative `WEBSITE_ENTITY_CONFIRMATION_COPY`; new-brief UI pending | AT-INTAKE-02 (copy assertion; UI assertion pending) | 5 | In progress |
| INTAKE-03 | Reject localhost/private/malformed/unsupported URLs | C2, C9 | `intake/url-policy.ts`; `mandate_worker.fetch.SafeFetcher` DNS/IP-pinned transport | AT-INTAKE-03 (preflight + pinned transport), SEC-03 (URL/IP/redirect/rebinding/budget table), ER-11 (private-IP redirect limitation and public-source recovery) | 1 | Implemented |
| INTAKE-04 | No confidential free-form descriptions or documents | C1, C2 | strict generated intake schema; body cap; mandatory ack in route/RPC; privacy-allowlisted `SearchRequest`, URL-only `PageFetchRequest`, identifier-only `ConfirmedCorporateFilingCommand`, and ModelGateway task payload allowlists; answer screening pending | AT-INTAKE-04 (route + DB ack + provider/command/gateway extra-field rejection), E2E-03 (pending) | 1/3 | In progress |
| INTAKE-05 | CIN optional | C1, C2 | generated contract; `report_requests.input_cin`; route/RPC | AT-INTAKE-05 (route + DB), ER-01 (exact CIN on controlled domain) | 1 | Implemented |
| INTAKE-06 | No entitlement reserved before entity confirmation | C2, C4 | identifier-only intake/resolve/refine commands; confirmation RPC and UI have no ledger surface; corporate-filing acquisition requires literal post-confirmation `preliminary_research`; reserve only in future `/generate` tx (QUEUE §4) | AT-INTAKE-06 (intake + confirmation + filing structural/database/UI foundations), E2E-01 and ledger invariant pending | 1/6 | In progress |

## Entity resolution

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| ENTITY-01 | Inspect website legal pages and disclosures | C6 (resolve stage), C9 | typed `LegalPageCrawler`/`PageInspection`; bounded priority discovery, robots handling, disclosure extraction, hidden-markup/script stripping, injection suspicion and stable fetch limitations | AT-ENTITY-01 (priority/robots/extraction), ER-01..11 deterministic website/registry suite | 1 | Implemented |
| ENTITY-02 | Candidates with supporting evidence | C6, C4 | typed `EntityCandidateGenerator`; generated `EntityCandidate`; atomic `entities`/`entity_candidates` persistence with evidence ids + factor audit; typed public-evidence relationship hints cannot affect scoring | AT-ENTITY-02 (verbatim scoring/evidence/dedupe/persistence), ER-01..11 deterministic suite | 1 | Implemented |
| ENTITY-03 | User confirmation mandatory | C1, C2, C4, C5 | literal `requiresUserConfirmation=true`; evidence-first candidate GET/UI with no preselection; strict confirmation contract; tenant-scoped idempotent `confirm_report_request_entity` RPC and guarded state transitions | AT-ENTITY-03 (generator, schemas, routes, UI, database mandatory-confirmation/state cases), E2E-01 pending | 1 | Implemented |
| ENTITY-04 | Ask for legal name/CIN when uncertain | C1, C2, C4 | typed `legal_name_or_cin_required`; no-match/exhaustion → `failed_no_charge`; none/refine UI/API; immutable intake plus separate public identity hints; retryable draft/failed recovery; state hint consumed by worker | AT-ENTITY-04 (no-match/no-charge/retry/API/UI), ER-09 no-disclosure outcome | 1 | Implemented |
| ENTITY-05 | CIN as exact identifier; compatible master-data sources | C8 (CompanyDataProvider), C4 | typed provider + deterministic registry fixtures; unsupported Attestr live selection fails closed; `entities.cin` unique and CIN-first identity key | AT-ENTITY-05 (provider/CIN/database identity), ER-01 exact-identifier case; live B5 gate remains phase-exit evidence | 1 | Implemented |
| ENTITY-06 | Brand never replaces legal entity in brief identity | C6 (composer), C4 | `entities.brand_names`; header rules (AGENT-PROMPT §7) | AT-ENTITY-06, ER-03, GC-09 | 4 | Specified |
| ENTITY-07 | Explain and confirm multi-entity scope | C1, C2, C4, C6 | typed public-evidence relationship hints; optional related-entity UI; strict confirm payload; `related_entity_ids` unique and ≤2; primary excluded; only explicitly proposed entities with a materiality reason accepted | AT-ENTITY-07 (relationship-hint validation, score isolation, schema/UI/database scope controls), ER-04 parent/opco case | 1 | Implemented |
| ENTITY-08 | Label primary and related entities separately | C6 (composer) | BriefDocument related-entity subsections (AS-10) | AT-ENTITY-08, GC-14 | 4 | Specified |

## Preliminary research and clarification

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| RESEARCH-01 | Preliminary research before contextual questions | C6 (pre-B stage) | light queue task; `report_requests.state` | AT-RESEARCH-01, E2E-03 | 3 | Specified |
| RESEARCH-02 | Only materially relevant questions | C6 (clarification planner) | `clarifications` payload | AT-RESEARCH-02 (planner eval) | 3 | Specified |
| RESEARCH-03 | Mandatory clarifications cannot be skipped | C1, C2 | `POST …/clarifications` validation | AT-RESEARCH-03, E2E-03 | 3 | Specified |
| RESEARCH-04 | Client role mandatory (4 options) | C1, C2 | `report_requests.client_role` enum | AT-RESEARCH-04, E2E-03 | 3 | Specified |
| RESEARCH-05 | Transaction type optional; overlay not limiter | C6 (planner/analyst) | `transaction_category`; AGENT-PROMPT §4/§6 | AT-RESEARCH-05, GC-10 | 3 | Specified |
| RESEARCH-06 | May ask foreign-investment question w/o confidential terms | C6 (planner) | `cross_border`; question templates | AT-RESEARCH-06 | 3 | Specified |
| RESEARCH-07 | Explain why each mandatory question matters | C1, C6 | `reason` field on questions | AT-RESEARCH-07, E2E-03 | 3 | Specified |

## Research execution

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| RUN-01 | Async, queue-driven generation | C5, C6 | outbox + pgmq (QUEUE §1/4) | AT-RUN-01, E2E-06 | 5 | Specified |
| RUN-02 | Truthful stage progress | C1, C6 | checkpoints → `GET /api/report-jobs/{id}` (QUEUE §7) | AT-RUN-02, E2E-06 | 5 | Specified |
| RUN-03 | Bounded business/industry/competitor/corporate/regulatory/public-risk/synthesis tasks | C6 | pipeline stages 2–10 | AT-RUN-03, GC suite | 2 | Specified |
| RUN-04 | Evidence stored separately from prose | C4 | `evidence`, `claims` vs `report_versions` | AT-RUN-04, E2E-02 | 2 | Specified |
| RUN-05 | Structured model outputs where feasible | C7 | `ModelGateway` validates caller-supplied Pydantic output schemas with exactly one bounded repair retry; deterministic fixture output is schema-checked | test_RUN_05_01, test_RUN_05_03, test_RUN_05_04 | 2 | Implemented |
| RUN-06 | Fetched content treated as untrusted | C8, C9, C6 | Exa results are discovery metadata only; robots-aware `PageFetcher` returns `evidence_admitted=false`; confirmation-gated filings remain quarantined; file-safety parsing returns `untrusted=true`, `evidence_admitted=false`; ModelGateway recursively rejects identity, firm, billing, letterhead, secret and confidential-matter keys and accepts only task-allowlisted identifiers/admitted content; stage-level untrusted envelopes remain pending | AT-RUN-06 foundations plus ModelGateway payload-rejection tests; SEC-04/ER-10 and SEC-05 foundations | 2 | In progress |
| RUN-07 | Per-report search/page/token/time/retry budgets | C6, C7, C8 | bounded Exa/PageFetcher/filing limits plus ModelGateway route token ceilings, call-cost ceiling and caller-supplied remaining job budget; orchestration-wide budget profile/stopping rules pending (QUEUE §8) | test_RUN_07_05 plus provider bounds/retry foundations | 2 | In progress |
| RUN-08 | Entity/provenance/consistency/length/safety quality gates | C6 (stage 11) | `quality_gate_result` (AGENT-PROMPT §10) | AT-RUN-08, QG fixtures | 4 | Specified |
| RUN-09 | Unrecoverable failure does not consume entitlement | C6, C4 | `failed_restored` side effects (QUEUE §5) | AT-RUN-09, E2E-08 | 6 | Specified |
| RUN-10 | Completion/failure email | C12 | `notification_log`; EmailProvider | AT-RUN-10, E2E-06/08 | 5 | Specified |

## Mandate Brief

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| REPORT-01 | Standard two-page target | C6 (length controller) | `lengthClass` default 2 (AGENT-PROMPT §8) | AT-REPORT-01 | 4 | Specified |
| REPORT-02 | Automatic 1–4-page main brief | C6, C10 | measured page count; trim protocol | AT-REPORT-02, GC-11 | 4 | Specified |
| REPORT-03 | Source annex outside page cap | C6, C10 | `sourceAnnex`; render measurement excludes annex | AT-REPORT-03, E2E-05 | 4 | Specified |
| REPORT-04 | Kickoff questions mandatory | C6 (analyst/composer) | `kickoff_questions` section; QG check | AT-REPORT-04, E2E-04 | 3 | Specified |
| REPORT-05 | "Matters for attention" heading | C6 (composer) | fixed section key/heading | AT-REPORT-05 | 4 | Specified |
| REPORT-06 | Distinguish fact/company claim/third-party/inference/conflict/unavailable | C6, C4 | `claims.claim_type`; block labels | AT-REPORT-06, QG | 2/4 | Specified |
| REPORT-07 | No definitive legal conclusions | C6 (composer + final verifier) | prohibited-phrasing checks | AT-REPORT-07, GC-03 | 4 | Specified |
| REPORT-08 | Dynamic research: last 3 FYs + current, or latest available | C6 | `claims.freshness` windows | AT-REPORT-08 | 2 | Specified |
| REPORT-09 | Historical facts may extend to incorporation | C6 | freshness classification | AT-REPORT-09 | 2 | Specified |
| REPORT-10 | Public-risk only where entity matching reliable | C6 (public-risk agent) | strong-identifier matching (AGENT-PROMPT §5) | AT-REPORT-10, GC-12 | 2 | Specified |

## Editing, letterhead and versions

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| EDIT-01 | Browser Mandate Brief editor | C1 | editor UI on `BriefDocument`; `POST …/versions` | AT-EDIT-01, E2E-09 | 4 | Specified |
| EDIT-02 | System draft immutable | C4 | `report_versions` v0 UPDATE-forbid trigger | AT-EDIT-02, E2E-09 | 4 | Specified |
| EDIT-03 | Version/reconstructable diff on save | C2, C4 | version chain (`parent_version_id`) | AT-EDIT-03, E2E-09 | 4 | Specified |
| EDIT-04 | Warn on unsupported user-added factual text | C1, C2 | origin flags + warnings (ADR-007) | AT-EDIT-04 | 4 | Specified |
| EDIT-05 | Revert to earlier version | C1, C2 | new version from old `document_json` | AT-EDIT-05 | 4 | Specified |
| EDIT-06 | Accept one-page PDF/image letterhead | C2, C13 | `POST …/letterhead`; `letterhead_assets` | AT-EDIT-06, SEC-05 | 4 | Specified |
| EDIT-07 | Never send letterhead to AI/search providers | C7, C13 | gateway payload allowlist; bucket isolation | AT-EDIT-07, E2E-09, SEC-11 | 4 | Specified |
| EDIT-08 | Preview letterhead-applied PDF | C1, C10 | render options + preview | AT-EDIT-08 | 4 | Specified |
| EDIT-09 | Letterhead ephemeral by default | C13 | `expires_at ≤24 h`; purge job | AT-EDIT-09, SEC-14 | 4 | Specified |
| EDIT-10 | Regeneration consumes new entitlement; editing does not | C2, C4 | regenerate = new request+reserve; versions free | AT-EDIT-10 | 6 | Specified |

## History and issue reporting

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| HISTORY-01 | Dashboard lists entity, status, created, last edited | C1 | `GET /api/reports`, `GET /api/report-requests` | AT-HISTORY-01 | 5 | Specified |
| HISTORY-02 | Reopen, edit, download or delete | C1, C2 | report endpoints + `DELETE /api/reports/{id}` | AT-HISTORY-02 | 5 | Specified |
| HISTORY-03 | No public share link | C2, C13 | signed short-lived URLs only; no share endpoint | AT-HISTORY-03, SEC-02 | 5 | Specified |
| ISSUE-01 | Issue categories (7) | C1, C2 | `report_issues.category` enum | AT-ISSUE-01, E2E-10 | 7 | Specified |
| ISSUE-02 | Preserve version and evidence references | C4 | `report_issues.report_version_id`, `evidence_refs` | AT-ISSUE-02, E2E-10 | 7 | Specified |
| ISSUE-03 | Admin restore entitlement + record root cause | C14 | admin issue endpoints; `restore` ledger event | AT-ISSUE-03, E2E-10 | 7 | Specified |
| ISSUE-04 | Correction creates a new version | C14, C4 | `admin_correction` version | AT-ISSUE-04, E2E-10 | 7 | Specified |

## Payments

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| PAY-01 | Razorpay | C11 | orders/webhook endpoints; `payments` | AT-PAY-01, E2E-07 | 6 | Specified |
| PAY-02 | Server-verified webhooks authoritative | C11 | HMAC + `webhook_events`; provisional client success | AT-PAY-02, SEC-06 | 6 | Specified |
| PAY-03 | Purchases create append-only entitlements | C4 | `purchase_grant` events; append-only enforcement | AT-PAY-03 | 6 | Specified |
| PAY-04 | Valid job reserves entitlement | C2, C4 | reserve+enqueue tx (QUEUE §4) | AT-PAY-04, E2E-07 | 6 | Specified |
| PAY-05 | Final quality completion consumes it | C6, C4 | consume gated on `quality_gate_result.passed` | AT-PAY-05, E2E-07 | 6 | Specified |
| PAY-06 | Failure/cancellation releases reservation | C6, C4 | `release` on terminal fail/cancel | AT-PAY-06, E2E-08 | 6 | Specified |
| PAY-07 | Unrecoverable single-report failure → refund or restore per policy | C11, C14 | refund flow + one-click offer | AT-PAY-07, E2E-08 | 6 | Specified |
| PAY-08 | Pack failures restore a credit | C6, C4 | `restore` event for pack purchases | AT-PAY-08, E2E-08 | 6 | Specified |
| PAY-09 | Webhooks idempotent | C11 | `razorpay_event_id` unique; ledger keys | AT-PAY-09, SEC-06 | 6 | Specified |
| PAY-10 | Refund and entitlement events auditable | C4, C14 | ledger + `admin_audit_log` + reconciliation | AT-PAY-10 | 6 | Specified |

## Admin panel

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| ADMIN-01 *(un-numbered in doc 02)* | Users, entitlements, jobs, queue, cost/brief, retries, provider errors, sources, entity candidates, issue queue, refunds/restorations, trial abuse, prompt/model versions, health | C14 | `/api/admin/*` (API §8) | AT-ADMIN-01 (panel coverage checklist), E2E-10 | 5–7 | Specified |

## Non-functional

| Req | Summary | Component | DB / API surface | Acceptance tests | Phase | Status |
|---|---|---|---|---|---|---|
| NFR-01 | Jobs retryable and idempotent | C5, C6 | request-scoped deterministic candidate ids; transactional outbox; idempotent completion/failure RPCs; private confirmation replay ledger; retryable refinement recovery; visibility retry/DLQ; later checkpoints (QUEUE §2/6) | AT-NFR-01 (light-task + confirmation foundations), E2E-05 | 2/5 | In progress |
| NFR-02 | Tenant isolation at database layer | C4 | forced RLS on every current table; owner-join candidate policy; service-only outbox/worker mutations; `auth.uid()`-derived confirmation RPC; private replay records (ERD §4) | AT-NFR-02, SEC-01 (database matrix expands with each table) | 0+ | In progress |
| NFR-03 | Containerised, Hostinger-independent worker | C6, C8 | `services/worker/Dockerfile`; `infra/compose/local.yml`; `mandate_worker.runtime`; `fixtures/demo` including corporate filings; `.github/workflows/ci.yml`; `scripts/generate_traceability_report.py`; no host coupling | AT-NFR-03 (structural + live portability/sandbox + complete zero-spend catalog check in CI stage 5; passing JUnit evidence enforced in CI stage 7) | 0 | Verified |
| NFR-04 | Trace ID across API/queue/model/search/payment/PDF | C15 | web-minted trace → validated outbox/light message → worker trace context; sink redaction (DEPLOYMENT §6); ModelGateway audit fields added; persisted propagation across model/payment/PDF pending | AT-NFR-04; SEC-09 (route/message/logger coverage) | 0+ | In progress |
| NFR-05 | Every external cost attributable to a report | C7, C8, C15 | provider call counts plus typed `AgentRunRecord` fields for report/job ids, model/provider, tokens, cost and latency; `provider_cost_events`/`agent_runs` persistence and admin view pending | provider foundations + ModelGateway cost/audit tests; persistence pending | 2 | In progress |
| NFR-06 | WCAG 2.1 AA target | C1 | axe checks in E2E; manual audit | AT-NFR-06 | 5/7 | Specified |
| NFR-07 | Interactive requests short; research async | C2, C5 | route-handler budget; queue offload | AT-NFR-07 (latency assertion) | 5 | Specified |
| NFR-08 | Deletion follows retention policy | C4, C6 | retention jobs (SECURITY §4) | AT-NFR-08, SEC-14 | 7 | Specified |
| NFR-09 | Store model IDs, prompt versions, parameters, evidence | C7, C4 | typed `AgentRunRecord` captures model/provider, prompt-bundle version, tokens, cost, latency and ZDR status; `agent_runs` table and evidence links pending next migration | ModelGateway audit-field tests; AT-NFR-09 persistence pending | 2 | In progress |
| NFR-10 | Add workers without redesigning job state | C5, C6 | stateless workers; DB-held state (QUEUE §1) | AT-NFR-10 (two-worker E2E) | 5 | Specified |

## MVP acceptance criteria (doc 02, composite)

| Criterion | Verified by |
|---|---|
| Entity confirmation | ER-01..11, E2E-01 |
| Durable queueing | E2E-05, E2E-06, AT-NFR-01 |
| Claim provenance | QG fixtures, E2E-04 |
| Entitlement restoration | E2E-08 |
| Versioned editing | E2E-09 |
| Safe letterhead rendering | SEC-05, E2E-09 |
| Reproducible PDF | E2E-05 |
| Tenant isolation | SEC-01 |
| Payment/provider cost reconciliation | E2E-07, AT-PAY-10, AT-NFR-05 |

**Coverage check:** 84 numbered requirements (AUTH 6, INTAKE 6, ENTITY 8, RESEARCH 7, RUN 10, REPORT 10, EDIT 10, HISTORY 3, ISSUE 4, PAY 10, NFR 10) + ADMIN-01 + the composite acceptance criteria — all rows present above; none `Verified` until its tagged tests pass in CI (TEST-PLAN §11).
