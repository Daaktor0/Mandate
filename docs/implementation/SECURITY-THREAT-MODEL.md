# SECURITY-THREAT-MODEL — Mandate

**Status:** Specified
**Sources:** product-specification docs 10 (authoritative — conflict-precedence rank 1), 05, 06, 04; master prompt security list
**Related:** [ERD.md](ERD.md) (RLS), [AGENT-PROMPT-SPEC.md](AGENT-PROMPT-SPEC.md) (injection), [TEST-PLAN.md](TEST-PLAN.md) (SEC tests)

This is a product/security specification, not a legal compliance opinion; Indian and cross-border law review is Blocker B10.

## 1. Assets and trust boundaries

Assets: user accounts and OAuth sessions; entitlement/payment integrity; Mandate Brief content and versions; letterhead files; evidence store; provider API keys; admin capabilities.

Trust boundaries: browser ↔ web API (untrusted client); web/worker ↔ external websites (hostile content); worker ↔ model providers (data-egress boundary); Razorpay ↔ webhook endpoint (spoofable caller); user uploads ↔ renderer (hostile files); admin ↔ system (privileged, audited).

## 2. Data classes and handling rules (doc 10)

| Class | Examples | Egress rule |
|---|---|---|
| Public research data | company site content, filings, regulator material, news, legal entity, CIN | may go to approved (ZDR, allowlisted) providers |
| Account/billing | name, email, phone, OAuth IDs, payments, entitlements | never to research/model/search providers |
| User work product | edits, issue text, versions | never to providers; training only with explicit opt-in consent |
| Firm branding | letterhead/logo | render-only; never to AI/search; encrypted at rest; ≤24 h |
| Prohibited MVP data | confidential documents/terms, privileged material | must not enter the system; screened at intake |

Enforcement is structural, not policy-only: the ModelGateway payload allowlist (ADR-005) admits only typed fields from public-research schemas; letterhead lives in a bucket no provider-facing code path can read; generic role/context strings replace identity ("prepared for an investor/acquirer", never the user's name/firm).

## 3. Threats and controls by surface

### 3.1 Authentication and tenant isolation (RLS/IDOR)

Threats: session theft, cross-tenant reads/writes via IDs, service-key leakage, privilege escalation to admin.
Controls: Supabase OAuth (Google/Microsoft) only; secure, httpOnly, SameSite cookies; RLS default-deny on every table (ERD §4); 404-indistinguishable responses for other users' resources; report IDs alone never authorise — signed storage URLs are short-lived and per-object (doc 10); no service-role key in frontend code or client bundles (CI secret-scan assertion); worker uses a least-privilege dedicated DB role; admin is a separate role checked server-side, all admin mutations audit-logged; quarterly access review.
Tests: SEC-01 (RLS/IDOR matrix over every endpoint: User A vs User B list/fetch/edit/render/download/delete), SEC-02 (signed-link expiry and cross-user reuse).

### 3.2 SSRF and hostile retrieval

Threats: intake URL or in-page link targets internal services (localhost, RFC1918, link-local, cloud metadata), redirect chains and DNS rebinding swap targets mid-request, oversized/streaming responses exhaust the worker.
Controls (ADR-011): scheme allowlist http/https; DNS resolve → IP vetting against private/reserved/metadata ranges → **connection pinned to the vetted IP**; re-vetting on every redirect (max 5); re-resolution attacks defeated by pinning; response size/time caps; content-type allowlist; Playwright confined by request interception to the same policy; per-domain and per-job crawl caps (doc 10 exhaustion controls).
Tests: SEC-03 (SSRF suite: localhost, 169.254.169.254, RFC1918, redirect-to-private, DNS-rebind simulation, IPv6 forms), AT-INTAKE-03.

### 3.3 Prompt injection

Threats: fetched pages instruct agents to exfiltrate secrets, fabricate claims, change scope, or poison entity resolution (doc 05 malicious-page acceptance case).
Controls: untrusted-envelope prompt architecture, injection rules in every system frame, deterministic script/hidden-text stripping, `prompt_injection_suspected` flagging with verifier awareness, agents have no secret material in context to leak, tool surface per stage is fixed (AGENT-PROMPT §11).
Tests: SEC-04 (injection corpus incl. GC-15 golden case; assertions: no instruction obedience, flag set, claims unaffected).

### 3.4 Malicious files (letterhead)

Threats: PDF with JS/embedded files/launch actions, polyglot images, decompression bombs, malware.
Controls: type/size allowlist (1-page PDF/PNG/JPG ≤10 MB); malware scan; **active-content stripping** — PDF letterheads are rasterised to images before stamping (removes JS/actions/attachments wholesale); sandboxed render step (no network, dropped privileges, resource-limited container); encrypted storage; `expires_at ≤ 24 h` purge (EDIT-09).
Tests: SEC-05 (hostile-file corpus), AT-EDIT-06/07/09.

### 3.5 Payments and webhooks

Threats: forged/replayed webhooks grant credits; race between webhook retries double-grants; client-side "success" trusted; refund fraud.
Controls: raw-body HMAC verification; `webhook_events` unique event-id (replay-safe); ledger idempotency keys; browser success is provisional only (PAY-02); amounts/packages fixed server-side; append-only ledger with invariants (ERD §5); reconciliation job against Razorpay reports; no card data stored.
Tests: SEC-06 (invalid signature, replay, out-of-order events), SEC-07 (concurrent reserve/consume/webhook races — property-based).

### 3.6 Trial and rate abuse

Threats: mass trial farming (disposable emails, virtual numbers), scripted request floods, cost-amplification via expensive generations.
Controls: ADR-013 trial gate (OAuth + phone OTP + disposable-email blocklist + device/IP velocity + CAPTCHA-when-risky + one per phone/person/risk-cluster + manual blocklist); per-user rate limits (API §1); per-job cost caps and global concurrency 2; admin trial-abuse view.
Tests: SEC-08 (trial duplication attempts across signals), AT-AUTH-06.

### 3.7 Secrets and logging

Threats: keys in images/repo/logs; PII or letterhead content in logs; verbose prompts logged.
Controls: secrets via environment/secret store only, never in images or repo (CI secret scanning + gitleaks pre-push); separate keys per environment; rotation runbook (DEPLOYMENT §8); structured logs limited to IDs, stages, durations, providers, token/cost, redacted errors; explicitly banned from logs: OAuth tokens, payment credentials, full prompts by default, letterhead bytes/derived text, user-added Mandate Brief text, secrets (doc 10); redaction helper applied at the logger boundary with unit tests.
Tests: SEC-09 (log-redaction assertions), SEC-10 (secret scan gate).

### 3.8 Model-provider privacy (ZDR)

Threats: provider trains on submitted data; non-allowlisted fallback; identity leakage in payloads.
Controls: per-request ZDR enforcement + provider allowlist at the gateway; providers that train on submitted data disabled; privacy routing logged (`agent_runs.zdr_enforced`); payload allowlist excludes identity/billing/branding; prompt logging at providers disabled; **fail-safe**: `NoApprovedCapacity` → retry_wait, never a silent non-approved fallback (doc 10).
Tests: SEC-11 (gateway property tests: forbidden-field injection attempts are rejected; ZDR flags asserted on every recorded call).

## 4. Retention and deletion jobs (doc 10 defaults; ERD §6)

Scheduled tasks (worker cron loop; schedules in DEPLOYMENT §7):

| Job | Schedule | Action |
|---|---|---|
| `purge_raw_pages` | daily | delete `evidence` raw bodies >30 days |
| `purge_letterheads` | hourly | delete expired `letterhead_assets` + storage objects |
| `prune_provider_logs` | daily | prune `agent_runs`/`provider_cost_events` >90 days (cost rollups retained) |
| `prune_audit_logs` | daily | prune `admin_audit_log` >180 days after review export |
| `prune_failed_diagnostics` | daily | strip failed-job checkpoints/details >30 days |
| `expire_entitlements` | daily | append `expiry` events for grants past validity |
| `reservation_sweep` | hourly | flag/release orphaned reservations (QUEUE §9) |
| `reconcile_ledger` | nightly | invariants check; ledger vs payments vs Razorpay |

**Account deletion** (AUTH-05): soft-delete profile, cancel active jobs with release, delete reports/versions/storage objects, tombstone billing/ledger for the legally required period, confirm scope to the user. **Report deletion** (HISTORY-02): version + storage purge, tombstone row retained (billing/security minimum).

## 5. Product-boundary controls (legal-risk surface)

The composer/verifier enforce: public-information-only statement, no legal advice/opinion/diligence claims, no completeness guarantees, independent-verification disclaimer verbatim, cautious allegation language, no unsupported MCA/legal-database claims (docs 06/07). Landing/marketing copy rules from doc 03 are release-checklist items, not code, but tested in AT-REPORT-07 and the golden suite.

## 6. Incident response (doc 10)

Ownership: founder is incident owner at MVP. Severity ladder: S1 cross-tenant data exposure / payment corruption / key compromise; S2 provider privacy breach, SSRF exploitation; S3 single-user data errors. Runbook per class: revoke/rotate keys (documented per provider in DEPLOYMENT §8), disable affected surface (feature flags), preserve evidence (DB snapshots, logs), notify affected users where required by law (B10 review), provider contacts list, backup restore procedure, post-incident review with root cause recorded in the issue tracker.

## 7. Pre-launch security test gate (doc 10 §pre-launch)

Release blocks until all pass (mapped in TEST-PLAN §6): RLS/IDOR (SEC-01/02), SSRF (SEC-03), prompt injection (SEC-04), malicious files (SEC-05), webhook replay (SEC-06), entitlement races (SEC-07), trial abuse (SEC-08), log redaction (SEC-09), secret scan (SEC-10), ZDR verification (SEC-11), dependency/container scans (SEC-12), rate limits (SEC-13), deletion/retention (SEC-14), backup restore (SEC-15).
