# 13 — Development Roadmap and Build Plan

## Principle

Build in this dependency order:

> correct entity → reliable evidence → useful questions → trusted Mandate Brief → safe billing.

Do not begin with a polished dashboard or theatrical multi-agent framework.

## Phase 0 — Engineering foundation

Monorepo/services, local/staging/production, CI, Docker worker, migrations, requirement traceability, observability, threat model and fixtures.

**Gate:** reproducible staging deployment, no secrets, baseline tests.

## Phase 1 — Entity-resolution proof of concept

Website/legal-name intake, URL safety, legal-page crawler, candidate extraction, company lookup adapter, confirmation UI and evidence. Test at least 30 varied companies.

**Gate:** ambiguous cases ask; no paid research before confirmation.

## Phase 2 — Evidence pipeline

Search/fetch adapters, source tiers, evidence/claim schemas, research tasks, prompt-injection defence, claim mapping, budgets and checkpoints.

**Gate:** evidence bundle reviewable without prose; all claims carry metadata.

## Phase 3 — Clarification and questions

Preliminary research, clarification planner, mandatory client role, optional transaction overlay, company/investor question logic and rubric.

**Gate:** lawyer-reviewed questions useful; no confidential narrative requested.

## Phase 4 — Mandate Brief composer and editor

Document schema, length controller, source annex, rendering, editor, immutable draft, versions, unsupported-user-text warning and letterhead.

**Gate:** no clipping; Mandate Brief reproducible; letterhead absent from model calls/logs.

## Phase 5 — Queue, accounts and notifications

Google/Microsoft login, dashboard, Supabase queue, Hostinger worker, progress, email, admin job view, cancel/retry.

**Gate:** worker restart recovery, tenant isolation and bounded concurrency.

## Phase 6 — Payments

Razorpay, entitlement ledger, reserve/consume/release, trial, packs/expiry, restoration, refund and reconciliation.

**Gate:** webhook replay safe, no double consume, failed jobs restore, refunds reconcile.

## Phase 7 — Quality and private beta

Automated gates, issue workflow, investigation, golden suite, cost dashboard, consented edit collection, retention/deletion and security tests.

**Paid-launch gate:** charter criteria, stable unit economics, reviewed terms/privacy and tested incident/refund procedures.

## End-to-end slices

1. website → candidate;
2. confirmed entity → evidence;
3. evidence → questions;
4. evidence + answers → Mandate Brief JSON;
5. Mandate Brief JSON → PDF;
6. account → queued report;
7. payment → entitlement → consume;
8. failure → restore/refund;
9. edit → version → letterhead PDF;
10. issue → investigation → correction.

## Do not build first

Workspaces, collaboration, unlimited group research, confidential uploads, small model, mobile app, visual agent canvas, all-country registries, direct MCA document purchase or deep analytics.

## Testing

Unit: URL safety, entity score, claims, length, ledger, freshness and routing. Integration: OAuth, search, OpenRouter, Razorpay, queue/storage, PDF and email. End-to-end: trial, paid reports, packs, ambiguity, worker crash, outage, wrong source, edit/revert, letterhead and refund.

## AI definition of done

Schema, prompt version, timeout/retry, cost, privacy route, failure state, evaluation, auditability and no chain-of-thought dependency.

## Founder validation

Interview 10–15 transaction lawyers, show a manual Mandate Brief, test page preference and ₹999 willingness, record actual questions, compare time saved and capture procurement/security objections.
