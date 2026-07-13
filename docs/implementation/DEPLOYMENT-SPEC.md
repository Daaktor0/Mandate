# DEPLOYMENT-SPEC — Environments, Hostinger, Operations and AWS Migration

**Status:** Specified
**Sources:** product-specification docs 08 (architecture/Hostinger/AWS), 10 (secrets/retention), 15 (vendors), 11 (budget)
**Related:** [SYSTEM-SPEC.md](SYSTEM-SPEC.md), [SECURITY-THREAT-MODEL.md](SECURITY-THREAT-MODEL.md)

## 1. Local development and zero-spend demo

Prerequisites: Docker, Node 22 + pnpm, Python 3.12 + uv, Supabase CLI.

```
supabase start                 # local Postgres/Auth/Storage/pgmq
pnpm install && pnpm -C apps/web dev
uv run -m mandate_worker       # or: docker compose -f infra/compose/local.yml up
```

**Demo mode (ADR-014):** `DEMO_MODE=1` wires every provider adapter to `fixtures/demo/` recordings and seeds a demo user with entitlements. The full flow — intake → candidates → confirmation → clarification → generation → editable Mandate Brief → PDF — runs **offline with zero API spend**. `make demo` brings up the stack, seeds, and prints a login link. CI runs the demo E2E suite on every PR.

## 2. Container layout (Compose, local ≙ Hostinger)

| Service | Image | Notes |
|---|---|---|
| `worker` | `services/worker` (Python 3.12-slim + Playwright Chromium + WeasyPrint + pinned fonts) | job loop + light-task loop + cron loop; FastAPI on :8081 (`/health`, `/metrics-lite`, internal only) |
| `renderer` | same image, separate container | sandboxed render profile: no network namespace access to providers, seccomp default, `mem_limit 1g`, read-only rootfs + tmpfs |
| `caddy` | caddy:2 | TLS termination, internal reverse proxy for health/uptime endpoints (and web app if ADR-016 lands on self-hosting) |
| `uptime-kuma` | optional | uptime + alert pings |

Resource limits on KVM 2 (2 vCPU / 8 GB / 100 GB NVMe — doc 15): worker 3 GB / 1.5 CPU, renderer 1 GB / 0.5 CPU, caddy 256 MB, kuma 256 MB; ~3 GB headroom. Two heavy jobs max (AS-05); Playwright bounded to one browser context at a time per job with 180 s/job budget.

## 3. Hostinger provisioning runbook (Blocker B9)

1. Create non-root deploy user; SSH key-only auth; disable password login and root SSH.
2. UFW: allow 22 (rate-limited), 80/443; default deny inbound. fail2ban on sshd.
3. Unattended security updates; Docker Engine 27 from Docker's repo.
4. Directory layout `/opt/mandate/{compose,env,backups}`; secrets in `/opt/mandate/env/*.env` (mode 600, deploy-user owned), **never** baked into images or the repo (doc 10).
5. `docker compose -f hostinger.yml --env-file /opt/mandate/env/prod.env up -d`.
6. Enable Hostinger VPS snapshots (weekly) + pre-deploy snapshot.
7. Healthcheck wiring: compose `healthcheck` per service; Uptime Kuma monitors `/health` and queue-age metric; alert to founder email/Telegram.

Explicit non-uses of this host (doc 08): no frontier inference, no unlimited browsers, no sole critical-data storage (Postgres/Storage live in Supabase), no synchronous public request serving for generation.

## 4. Deployment procedure

GitHub Actions on `main`: lint → typecheck → unit → integration (local Supabase service container) → demo E2E → build/push images (GHCR, tagged by SHA) → staging deploy (SSH: pull images, `docker compose up -d`, run pending Supabase migrations via CLI, smoke test `/health` + one fixture job) → manual approval → production deploy (same steps + pre-deploy snapshot).

Rollback: images are SHA-tagged — `docker compose` back to previous SHA; migrations are expand/contract (additive first; destructive steps in a later release) so the previous app version always runs against the current schema. Migration rollback beyond that = restore from Supabase PITR + snapshot (documented, tested in SEC-15).

## 5. Environment variables (full inventory)

| Variable | Scope | Purpose |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | web | client SDK (anon key is RLS-bound, safe for client) |
| `SUPABASE_SERVICE_ROLE_KEY` | web API (server-only) | privileged paths (ledger writes); never shipped to client |
| `SUPABASE_DB_URL_WORKER` | worker | dedicated least-privilege DB role (not service role) |
| `SUPABASE_STORAGE_BUCKET_REPORTS` / `_LETTERHEADS` / `_EVIDENCE` | web+worker | bucket names; letterheads bucket encrypted, no provider-path access |
| `QUEUE_BACKEND` | worker | `pgmq` \| `sqs` \| `memory` |
| `DEMO_MODE` | all | `1` = all-fixture wiring, zero spend |
| `PROVIDER_SEARCH` | worker | `brave` \| `tavily` \| `exa` \| `fixture` (+ `SEARCH_API_KEY`) |
| `PROVIDER_COMPANY_DATA` | worker | `attestr` \| `sandbox` \| `probe42` \| `fixture` (+ key) |
| `OPENROUTER_API_KEY` | worker | model gateway |
| `MODEL_ROUTING_CONFIG` | worker | path to versioned routing yaml |
| `BUDGET_PROFILE_CONFIG` | worker | budget caps file |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` / `RAZORPAY_WEBHOOK_SECRET` | web API | payments (test keys in staging) |
| `EMAIL_PROVIDER` (+ key, from-domain) | worker | `resend` \| `ses` \| `console` |
| `SMS_PROVIDER` (+ key) | web API | phone OTP (Blocker B8) |
| `APP_BASE_URL` | all | links in emails |
| `TRIAL_COHORT_CAP` | web API | 100 (AS-14) |
| `PRICING_CONFIG` | web API | package codes → amount/validity (server-fixed; FOUNDER_CONFIRM B13) |
| `LOG_LEVEL` / `TRACE_SAMPLING` | all | observability |
| `WORKER_CONCURRENCY_HEAVY` / `_LIGHT` | worker | 2 / 2 |

Per-environment files: `local.env` (defaults, demo), `staging.env`, `prod.env`. Rotation runbook per key in §8.

## 6. Observability (NFR-04/05)

- **Trace ID** minted at request creation, propagated web → outbox → queue message → worker stages → model gateway → payment/webhook handlers → PDF/email; on every log line and API response header.
- **Structured JSON logs** to stdout → `docker logs` + optional Loki later; redaction at logger boundary (SEC-09).
- **Metrics** (worker `/metrics-lite`, admin overview): queue depth and oldest-message age, active jobs, per-stage durations, model/search spend per job and per day, error rates by provider, PDF/webhook failures, entitlement-reconciliation status, quality-gate pass rate, CPU/RAM (host node-exporter optional).
- **Cost attribution:** every external call writes `provider_cost_events` with `job_id` — cost per successful Mandate Brief is a first-class admin metric (doc 08 cost control; NFR-05). Daily spend caps: gateway refuses new jobs past a configurable daily model-spend ceiling; admin alert at 80%.

## 7. Scheduled operations

Retention/reconciliation jobs from SECURITY §4 run in the worker's cron loop (single-instance lock via Postgres advisory lock). Schedule table mirrors that section; failures alert via Uptime Kuma heartbeat misses.

## 8. Backup, recovery and key rotation

- **Postgres/Storage:** Supabase daily backups + PITR (plan-dependent); restore procedure documented and rehearsed (SEC-15).
- **Host:** weekly + pre-deploy snapshots; compose + env files backed up encrypted off-host.
- **Recovery targets [implementation addition]:** RPO ≤24 h (PITR typically better), RTO ≤4 h for full stack re-provision (runbook-timed).
- **Key rotation runbook:** per provider (Supabase keys, OpenRouter, search, company-data, Razorpay, email, SMS): where issued, where stored, rotation steps, blast radius, verification. Rotation cadence: 90 days or on incident.

## 9. Monthly cost model (prototype)

Doc 08 (~₹1,000/month incremental) is feasible only for low-volume testing on existing Hostinger + free/low-cost tiers:

| Item | Prototype assumption |
|---|---|
| Hostinger KVM 2 | already owned (sunk) |
| Supabase | free/dev tier initially; Pro (~US$25) before beta with PITR needs |
| OpenRouter | pay-as-you-go; capped by daily ceiling; est. ₹15–60/brief until measured |
| Search provider | free/trial credits during benchmark (B4) |
| Company-data API | trial tier (B5) |
| Email/SMS | negligible at test volume |

The 30-brief measurement (Phase 2/7, doc 11) replaces these assumptions with data; paid launch must not depend permanently on free tiers (doc 08).

## 10. AWS Mumbai migration map (doc 08)

| MVP | AWS | Adapter/port |
|---|---|---|
| Supabase Queues (pgmq) | SQS | `QueueAdapter` (ADR-002) |
| Hostinger worker | ECS Fargate | container is stateless between checkpoints already |
| Supabase Storage | S3 | `StorageAdapter` |
| Supabase Postgres | RDS/Aurora | standard PG migration; RLS carries over |
| Supabase Auth | retained or Cognito (decide at migration) | auth is cookie/JWT-boundary isolated |
| Logs | CloudWatch | stdout JSON already structured |
| Rate limiting | ALB/WAF | complements app-level limits |
| Secrets | Secrets Manager | env-injection unchanged |
| Cron loop | EventBridge Scheduler | same job entrypoints |

Migration preconditions enforced now: worker stateless between checkpoints, containerised, interface-driven providers, no Hostinger-specific dependencies (NFR-03). Trigger: load or security needs justify it (doc 08).
