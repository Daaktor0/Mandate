# SYSTEM-SPEC — Mandate MVP System Specification

**Status:** Specified
**Sources:** product-specification docs 01, 02, 08, 09, 13, 16
**Related:** [ARCHITECTURE-DECISIONS.md](ARCHITECTURE-DECISIONS.md), [ERD.md](ERD.md), [DEPLOYMENT-SPEC.md](DEPLOYMENT-SPEC.md)

## 1. System overview

Mandate converts a company website or legal name into a source-backed, editable **Mandate Brief** for Indian corporate transaction lawyers. The system is an evidence pipeline with model-assisted reasoning, not a chatbot:

1. A user signs in with Google or Microsoft and submits a website URL or legal name (optional CIN).
2. The **entity resolver** identifies candidate legal entities; the user **must confirm** one before any paid research (ENTITY-03, INTAKE-06).
3. Preliminary research feeds a **clarification** step (mandatory client role; optional transaction overlay).
4. An entitlement is atomically **reserved** and a generation job is **enqueued**.
5. A queued Python worker runs bounded, typed research stages against public sources through provider adapters and an OpenRouter-backed model gateway, storing **evidence separately from prose**.
6. Verifiers gate the output; the **composer** produces a 1–4 page Mandate Brief document with mandatory kickoff questions and a source annex; the renderer produces a PDF.
7. On quality-gate pass, the entitlement is **consumed** and the user is emailed. On terminal failure it is **released/restored** (RUN-09, PAY-06).
8. The user edits (versioned; system draft immutable), optionally applies a render-only letterhead, and downloads the PDF.

## 2. Component inventory

| # | Component | Runtime | Responsibility | Key requirement families |
|---|---|---|---|---|
| C1 | **Web app** | Next.js (Node.js), browser | Landing, auth UI, dashboard, intake, entity confirmation, clarifications, progress, Mandate Brief editor, letterhead, download, issue reporting | INTAKE, ENTITY (UI), RESEARCH (UI), REPORT (display), EDIT, HISTORY, ISSUE |
| C2 | **Web API** | Next.js route handlers | Short request/response APIs only (NFR-07); request validation; RLS-scoped data access; enqueue via entitlement transaction | INTAKE, ENTITY, RESEARCH, RUN-01, EDIT, HISTORY, ISSUE, PAY |
| C3 | **Auth** | Supabase Auth | Google OAuth, Microsoft/Azure OAuth, session cookies, phone OTP for trial eligibility | AUTH-01..06 |
| C4 | **Database** | Supabase Postgres 15 + RLS | Source of truth: entities, requests, jobs, checkpoints, evidence, claims, reports, versions, ledger, payments | NFR-02, NFR-08, PAY-03, EDIT-02/03 |
| C5 | **Queue** | Supabase Queues (pgmq) + outbox table | Durable job delivery, leases, retries; abstracted behind `QueueAdapter` for SQS portability | RUN-01, NFR-01, NFR-10 |
| C6 | **Worker** | Python 3.12 container on Hostinger KVM 2 | Job leasing, research pipeline orchestration, checkpointing, budget enforcement, quality gates, composition, rendering trigger, email trigger | RUN-*, REPORT-* (generation), NFR-01/03/04/05/09 |
| C7 | **Model gateway** | Python module inside worker | Task→model routing, ZDR enforcement, provider allowlist, structured-output validation, token/cost caps, usage logging, identity exclusion | RUN-05/07, NFR-05/09, security doc 10 |
| C8 | **Provider adapters** | Python modules | `SearchProvider`, `PageFetcher`, `CompanyDataProvider`, `RegulatorySourceAdapter`, `LitigationSourceAdapter`, `ModelRouter`, `QueueAdapter`, `StorageAdapter`, `EmailProvider` — each with fixture/mock implementations | RUN-06/07, ENTITY-05, NFR-03 |
| C9 | **Safe fetcher/extractor** | Python (httpx + bounded Playwright + Trafilatura/BeautifulSoup) | SSRF-guarded fetching, content extraction, evidence capture, prompt-injection flagging | INTAKE-03, RUN-06, security doc 10 |
| C10 | **PDF renderer** | Python (WeasyPrint + pypdf) in worker container | Deterministic Mandate Brief HTML→PDF, letterhead overlay (render-only), continuation pages | REPORT-01..03, EDIT-06..09 |
| C11 | **Payments** | Razorpay Checkout + webhook handler (C2) + ledger (C4) | Server-created orders, verified idempotent webhooks, append-only entitlement ledger, refunds | PAY-01..10 |
| C12 | **Email** | Transactional email adapter | Completion/failure notifications | RUN-10 |
| C13 | **Storage** | Supabase Storage | PDFs, source annexes, limited evidence snapshots, short-lived letterheads; signed short-lived links | EDIT-06..09, HISTORY-02 |
| C14 | **Admin panel** | Next.js (admin role) | Users, entitlements, jobs, queue, cost per Mandate Brief, retries, provider errors, entity candidates, issue queue, refunds/restorations, trial abuse, prompt/model versions, health | ADMIN-01, ISSUE-03 |
| C15 | **Observability** | Structured logs + health endpoints + Uptime Kuma (optional) | Trace ID propagation, stage/cost metrics, reconciliation dashboards | NFR-04, NFR-05 |

## 3. Repository structure (monorepo)

```
Mandate/
├── apps/
│   └── web/                      # C1, C2, C14 — Next.js + TypeScript
│       ├── app/                  # routes: (marketing), (app), (admin), api/
│       ├── components/
│       ├── lib/                  # supabase clients, validation, api helpers
│       └── tests/
├── services/
│   └── worker/                   # C6–C10 — Python 3.12
│       ├── mandate_worker/
│       │   ├── pipeline/         # typed stages (see AGENT-PROMPT-SPEC)
│       │   ├── agents/           # per-agent prompt + schema + runner
│       │   ├── providers/        # adapter interfaces + real + fixture impls
│       │   ├── gateway/          # model gateway (C7)
│       │   ├── fetch/            # safe fetcher/extractor (C9)
│       │   ├── render/           # brief HTML → PDF, letterhead overlay (C10)
│       │   ├── queue/            # QueueAdapter impls (pgmq, sqs, memory)
│       │   ├── budgets.py
│       │   ├── checkpoints.py
│       │   └── main.py           # FastAPI health/admin + job loop
│       └── tests/
├── packages/
│   └── shared-schemas/           # contract-first JSON Schemas (ADR-008)
│       ├── schemas/*.json        # source of truth
│       ├── typescript/           # generated TS types (zod)
│       └── python/               # generated Pydantic models
├── supabase/
│   ├── migrations/               # SQL migrations incl. RLS policies
│   ├── seed/                     # local seed data
│   └── config.toml
├── fixtures/
│   ├── golden/                   # golden-case inputs + expected outcomes (GC-*)
│   └── demo/                     # zero-spend demo fixtures (recorded provider responses)
├── infra/
│   ├── compose/                  # docker-compose.yml (local + hostinger)
│   ├── caddy/
│   └── scripts/                  # deploy, backup, retention jobs
├── docs/
│   └── implementation/           # this directory
└── product-specification/        # authoritative product spec (existing)
```

## 4. Pinned toolchain and versions

Exact patch versions are pinned in lockfiles at Phase 0; the table pins the supported major/minor lines. **[implementation addition]** — versions chosen current-stable as of 2026-07; upgrades require a passing golden-suite run.

| Area | Technology | Version line |
|---|---|---|
| Web runtime | Node.js | 22 LTS |
| Web framework | Next.js | 15.x (App Router) |
| Language | TypeScript | 5.8.x |
| UI | React | 19.x |
| Validation (web) | zod | 3.x (generated from shared schemas) |
| Package manager (JS) | pnpm | 10.x (workspaces) |
| Worker runtime | Python | 3.12.x |
| Worker API | FastAPI | ≥0.115 |
| Worker models | Pydantic | 2.x |
| HTTP client | httpx | 0.28.x |
| Browser extraction | Playwright (Python) | 1.5x, Chromium only, bounded |
| Text extraction | Trafilatura / BeautifulSoup4 | 2.x / 4.13.x |
| PDF | WeasyPrint + pypdf | 69.x / 6.x |
| Package manager (Py) | uv | 0.7.x |
| Database | Supabase Postgres | 15.x |
| Queue | pgmq (Supabase Queues) | 1.x |
| Payments | Razorpay Python/Node SDK | current stable |
| Containers | Docker Engine + Compose | 27.x / v2 |
| Reverse proxy | Caddy | 2.x |
| Lint/format | ESLint 9 + Prettier 3 (web); Ruff (worker) | — |
| Tests | Vitest + Playwright Test (web); pytest (worker) | — |
| CI | GitHub Actions | — |

## 5. Environments

| Environment | Web | Database/Queue/Storage | Worker | Providers |
|---|---|---|---|---|
| **local** | `next dev` | Supabase CLI (local stack) | Compose service | Fixture adapters by default (`DEMO_MODE=1`, zero spend) |
| **staging** | Vercel preview/branch deployment (ADR-016) | Supabase project (staging) | Hostinger KVM 2, Compose | Real adapters, test keys, low caps |
| **production** | Vercel production deployment (ADR-016) | Supabase project (production) | Hostinger KVM 2, Compose | Real adapters, live keys, enforced caps |

Rules: separate Supabase projects and secrets per environment; no service-role key in the frontend; the database is the source of truth in all environments.

## 6. Requirement-family ownership

| Family | Owning components | Spec detail |
|---|---|---|
| AUTH-01..06 | C3, C1, C4 | API-SPEC §2, SECURITY §4 |
| INTAKE-01..06 | C1, C2, C9 | API-SPEC §3, AGENT-PROMPT §3 |
| ENTITY-01..08 | C6 resolver stage, C1, C4 | AGENT-PROMPT §3, ERD §entities |
| RESEARCH-01..07 | C6 supervisor/clarification stages, C1 | AGENT-PROMPT §4–5 |
| RUN-01..10 | C5, C6, C7, C12 | QUEUE-AND-JOB-SPEC |
| REPORT-01..10 | C6 composer/verifier, C10 | AGENT-PROMPT §6–8 |
| EDIT-01..10 | C1, C2, C4, C10, C13 | API-SPEC §6, ERD §report_versions |
| HISTORY-01..03 | C1, C2, C4 | API-SPEC §7 |
| ISSUE-01..04 | C1, C2, C14 | API-SPEC §8 |
| PAY-01..10 | C11, C2, C4 | API-SPEC §9, ERD §entitlement_ledger |
| ADMIN-01 | C14 | API-SPEC §10 |
| NFR-01..10 | cross-cutting | QUEUE, SECURITY, DEPLOYMENT specs |

Full per-requirement mapping: [REQUIREMENTS-TRACEABILITY.md](REQUIREMENTS-TRACEABILITY.md).

## 7. Naming rules

- User-facing: **Mandate** (product), **Mandate Brief** (report), "Matters for attention" (REPORT-05), the seven progress stages of doc 03 verbatim.
- Technical: `reports`, `report_jobs`, `report_versions`, `report_requests` etc. are acceptable internal names (doc 16). API paths follow doc 09 (`/api/report-requests`, `/api/reports/...`).
- Never in user-facing copy: "tokens", "agents/agent diagrams", diligence/legal-advice claims (doc 03 landing rules).

## 8. Hard boundaries the system must respect

These override any implementation convenience (conflict-precedence rule 1):

1. Public information only; no confidential uploads or free-form confidential descriptions (INTAKE-04).
2. User identity, firm, billing and letterhead data are never sent to model or search providers (doc 10; EDIT-07).
3. ZDR and provider allowlisting enforced per model request; fail safe when no approved capacity exists.
4. No entitlement reservation before entity confirmation (INTAKE-06); no consumption before quality-gate pass (PAY-05).
5. System Mandate Brief drafts are immutable (EDIT-02); all billing events are append-only and idempotent (PAY-03/09).
6. Hidden chain-of-thought is neither stored nor exposed; store evidence, structured decisions, concise rationales and audit metadata (doc 04).
7. Retrieval must not bypass paywalls/CAPTCHAs, impersonate users, or use user credentials (doc 06).
