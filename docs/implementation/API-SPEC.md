# API-SPEC — Mandate Web API

**Status:** Specified
**Sources:** product-specification docs 09 (endpoint outline), 02 (requirements), 03 (screens/states), 10 (security), 11 (payments)
**Related:** [ERD.md](ERD.md), [QUEUE-AND-JOB-SPEC.md](QUEUE-AND-JOB-SPEC.md)

## 1. Conventions

- All endpoints are Next.js route handlers under `/api/*`, **short request/response only** (NFR-07); anything long-running is enqueued.
- Auth: Supabase session cookie (Google/Microsoft OAuth). Every handler resolves `auth.uid()`; data access goes through RLS-scoped clients. Admin endpoints additionally require `is_admin` and log to `admin_audit_log`.
- Content type `application/json`; request/response bodies validated with zod schemas generated from `packages/shared-schemas`.
- **Error model** (all non-2xx):

```json
{ "error": { "code": "ENTITY_NOT_CONFIRMED", "message": "human-safe text", "traceId": "…" } }
```

  Codes are stable strings; messages never leak internals, provider names, or other users' data. 401 unauthenticated, 403 RLS/ownership, 404 not-found-or-not-yours (indistinguishable, anti-IDOR), 409 state conflicts, 422 validation, 429 rate limit.
- **Idempotency:** mutating endpoints marked ⚑ accept an `Idempotency-Key` header; replays return the original result. Webhooks and internal ledger writes have their own key scheme (ERD §5.6).
- **Rate limits** (per user unless noted): intake/resolve 10/h; generate 6/h; render 20/h; letterhead upload 10/h; issues 10/d; payments orders 10/h; webhook endpoint IP-allowlisted to Razorpay + signature-verified. 429 with `Retry-After`.
- **Pagination:** `?cursor=`&`?limit=` (default 20, max 100), response `{ items, nextCursor }`.
- **Trace:** every response carries `X-Trace-Id` (NFR-04).

## 2. Auth and account

Login/OAuth is handled by Supabase Auth (AUTH-01/02); these endpoints cover profile and account lifecycle.

| Endpoint | Purpose |
|---|---|
| `GET /api/me` | Profile + entitlement summary: `{ profile, entitlements: { available, reserved, consumed, restored, expired } }` (AUTH-04, from ledger view) |
| `PATCH /api/me` | First-login fields: name, country, role, terms/privacy acceptance |
| `POST /api/me/phone/verify-start` ⚑ / `POST /api/me/phone/verify-check` | Phone OTP for trial eligibility (AUTH-06) |
| `POST /api/me/trial-claim` ⚑ | Grants trial entitlement if eligible (cohort cap, risk checks — ADR-013); 409 `TRIAL_INELIGIBLE` otherwise |
| `DELETE /api/account` ⚑ | Soft-deletes account per retention policy (AUTH-05); active jobs are cancelled → `cancelled_restored`; returns what is retained and why |

## 3. Report requests, intake and entity resolution

### `POST /api/report-requests` ⚑

Creates a request in `draft`. Body: `{ inputKind: "website"|"legal_name", url?, legalName?, cin?, confidentialAck: true }`.
Validation: exactly one of `url`/`legalName`; URL rejected if localhost/private-network/malformed/unsupported scheme (INTAKE-03, checked again server-side with the SafeFetcher policy); no free-form description field exists (INTAKE-04); `confidentialAck` required. **No entitlement is touched** (INTAKE-06).
→ `201 { reportRequest }`.

### `POST /api/report-requests/{id}/resolve-entity` ⚑

Transitions `draft → resolving_entity`; enqueues the (unpaid) resolution task. 409 unless state is `draft` or a re-resolve after `None of these` / added CIN. → `202 { state }`.

### `GET /api/report-requests/{id}/entity-candidates`

→ `{ state, candidates: EntityCandidate[] }` ordered by rank, with evidence snippets and confidence labels for the confirmation cards (doc 03). While resolution runs: `{ state: "resolving_entity", candidates: [] }`.

### `POST /api/report-requests/{id}/confirm-entity` ⚑

Body one of:
- `{ action: "confirm", candidateId, relatedEntityIds?: [] }` — ≤2 related entities, each requiring explicit inclusion (ENTITY-07/08). → `awaiting_entity_confirmation → preliminary_research`, enqueues preliminary research.
- `{ action: "none_of_these" }` → back to `draft` with guidance to add legal name/CIN (ENTITY-04). No charge (doc 05 failure rules).
- `{ action: "refine", legalName?, cin?, state? }` → re-resolution with added identifiers.

Confirmation is mandatory; no path skips it (ENTITY-03).

### `GET /api/report-requests/{id}/clarifications`

→ `{ state, questions: ClarificationQuestion[] }` — planner output; each mandatory question includes `reason` (RESEARCH-07). Available once state is `awaiting_clarification`.

### `POST /api/report-requests/{id}/clarifications` ⚑

Body: `{ answers: { clientRole: …, transactionCategory?, crossBorder?, knownIssue? } }`. `clientRole` required (RESEARCH-03/04); free-text fields are length-capped and screened for confidential-content patterns with a warning-and-reject rule (INTAKE-04). Does **not** reserve entitlement yet.

### `POST /api/report-requests/{id}/generate` ⚑

Preconditions: state `awaiting_clarification` answered; confirmed entity; sparse-data disclosure acknowledged if flagged (doc 03). Executes the **reserve+enqueue transaction** (ADR-010): reserve entitlement (409 `NO_ENTITLEMENT` if balance 0, offering purchase), create `report_jobs` row, outbox enqueue, state → `queued`.
→ `202 { jobId, state: "queued" }`.

### `GET /api/report-requests` / `GET /api/report-requests/{id}`

List/detail for dashboard (HISTORY-01): entity, status, created, last edited.

## 4. Jobs and progress

### `GET /api/report-jobs/{id}`

→ `{ status, stages: [{ key, label, completedAt }...], currentStageLabel, failure?: { code, userMessage, entitlementOutcome } }` — built from checkpoints via `job_progress_view`; labels are the seven doc-03 stages (RUN-02, ADR-012). Never exposes internal reasoning, provider names or costs.

### `POST /api/report-jobs/{id}/cancel` ⚑

Allowed while `queued` (and best-effort during `running` at stage boundaries); releases reservation → `cancelled_restored`.

## 5. Reports (Mandate Briefs)

| Endpoint | Purpose |
|---|---|
| `GET /api/reports` | Dashboard list (HISTORY-01) |
| `GET /api/reports/{id}` | Metadata + current/system version ids + `researchCurrentTo` + page count |
| `GET /api/reports/{id}/versions` / `GET /api/reports/{id}/versions/{versionId}` | Version list / full `BriefDocument` JSON (EDIT-05 revert reads an old version) |
| `POST /api/reports/{id}/versions` ⚑ | Save edit: `{ parentVersionId, documentJson }`. Server validates schema, recomputes `origin` flags, rejects edits claiming `origin:"system"` on changed blocks, stores unsupported-user-text warnings (EDIT-01/03/04). System draft is never writable (EDIT-02) |
| `POST /api/reports/{id}/render` ⚑ | `{ versionId, options: { includeAnnex, letterheadAssetId? } }` → `202` render task (re-render never reruns research — doc 03); result surfaced on the version (`renderedPdfKey`) |
| `GET /api/reports/{id}/download?versionId=` | → `{ signedUrl, expiresAt }` short-lived signed link (doc 10); no public share links exist (HISTORY-03) |
| `DELETE /api/reports/{id}` ⚑ | User deletion → tombstone per retention (HISTORY-02, NFR-08) |

### Letterhead

`POST /api/reports/{id}/letterhead` ⚑ — multipart upload, 1 page PDF / PNG / JPG, ≤10 MB (EDIT-06). Pipeline: type/size allowlist → malware + active-content scan → sanitised storage with `expires_at ≤ 24 h` (EDIT-09). → `{ letterheadAssetId, scanStatus }`. The asset id is only ever consumed by the renderer; no model/search code path can read the bucket (EDIT-07, enforced by storage policy + gateway payload allowlist).
`DELETE /api/reports/{id}/letterhead/{assetId}` — immediate purge.

## 6. Issues

`POST /api/reports/{id}/issues` ⚑ — `{ versionId, category, description, highlightedText? }`, categories per ISSUE-01; version pinned (ISSUE-02).
`GET /api/reports/{id}/issues` — user's issues + status/resolution.

## 7. Payments

### `POST /api/payments/orders` ⚑

Body: `{ packageCode: "single"|"pack5"|"pack10" }`. Server fixes amount/package from config (never client-priced), creates Razorpay order → `{ razorpayOrderId, amount, currency, keyId }` (doc 11).

### `POST /api/payments/confirm`

Browser success callback → marks payment **provisional** only; UI shows "confirming payment". Authoritative state comes from the webhook (PAY-02).

### `POST /api/webhooks/razorpay`

Unauthenticated route with: raw-body HMAC signature verification (reject otherwise), `razorpay_event_id` uniqueness via `webhook_events` (replay-safe, PAY-09), then idempotent processing: `payment.captured` → insert payment update + `purchase_grant` ledger events (PAY-03) with `idempotency_key = webhook:{event_id}`; `refund.processed` → refund row + `refund_reversal` where policy applies. Always `200` after durable recording; processing failures are retried from the stored event (never re-delivered state from Razorpay is trusted over DB).

### `GET /api/payments`

Payment history for dashboard (doc 03).

## 8. Admin API (`/api/admin/*`, admin role + audit-logged)

Backing ADMIN-01 and ISSUE-03. All read endpoints paginated/filterable.

| Endpoint | Purpose |
|---|---|
| `GET /api/admin/overview` | Health: queue depth, active jobs, error rates, webhook failures, reconciliation status |
| `GET /api/admin/users` / `GET /api/admin/users/{id}` | Users, entitlement summaries, trial risk flags |
| `POST /api/admin/users/{id}/block-trial` ⚑ | Trial-abuse blocklist |
| `GET /api/admin/jobs` / `GET /api/admin/jobs/{id}` | Jobs with stages, retries, provider errors, per-stage cost, model/prompt versions (NFR-09); the doc-09 audit question answerable from this single view |
| `POST /api/admin/jobs/{id}/retry` ⚑ / `POST /api/admin/jobs/{id}/cancel` ⚑ | Requeue from last checkpoint / cancel with release |
| `GET /api/admin/requests/{id}/entity-candidates` | Resolution debugging |
| `GET /api/admin/costs` | Cost per Mandate Brief, provider breakdown, cap status (NFR-05) |
| `GET /api/admin/issues` / `PATCH /api/admin/issues/{id}` ⚑ | Issue queue: investigate, record `root_cause`, resolve (ISSUE-03) |
| `POST /api/admin/issues/{id}/restore-entitlement` ⚑ | Ledger `restore` with reason; audit-logged |
| `POST /api/admin/issues/{id}/publish-correction` ⚑ | Creates `admin_correction` report version (ISSUE-04); original preserved |
| `POST /api/admin/refunds` ⚑ | Initiate/track refunds (PAY-07/10) |
| `GET /api/admin/reconciliation` | Ledger vs payments vs Razorpay reconciliation report |

## 9. Endpoint → requirement map (summary)

| Endpoint group | Requirements |
|---|---|
| §2 account | AUTH-03/04/05/06 |
| §3 intake/resolution | INTAKE-01..06, ENTITY-01..08, RESEARCH-01..07, PAY-04 |
| §4 jobs | RUN-01/02, PAY-06 |
| §5 reports/letterhead | REPORT-01..03 (display), EDIT-01..10, HISTORY-01..03 |
| §6 issues | ISSUE-01/02/04 |
| §7 payments | PAY-01..03, PAY-07..10 |
| §8 admin | ADMIN-01, ISSUE-03, NFR-05/09 |

Full matrix: [REQUIREMENTS-TRACEABILITY.md](REQUIREMENTS-TRACEABILITY.md).
