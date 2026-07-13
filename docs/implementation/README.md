# Mandate — Implementation Specification Set

**Product:** Mandate
**Flagship report:** Mandate Brief
**Status:** Specification complete — Phase 0 engineering foundation implemented and Gate G0 passed
**Derived from:** [`product-specification/`](../../product-specification/README.md) (authoritative)
**Last updated:** 2026-07-13

This directory converts the Mandate product specification into an executable technical specification, as required by the first deliverable of the [Fable 5 master prompt](../../product-specification/prompts/FABLE-5-SPEC-AND-BUILD-PROMPT.md). Implementation follows the phase order and evidence gates in [BUILD-CHECKLIST.md](BUILD-CHECKLIST.md); Phase 0 is complete and its evidence is recorded in [the Gate G0 record](gates/G0-engineering-foundation.md).

## Document map

| Document | Contents |
|---|---|
| [SYSTEM-SPEC.md](SYSTEM-SPEC.md) | Component inventory, repository structure, pinned versions, environments, naming rules |
| [ARCHITECTURE-DECISIONS.md](ARCHITECTURE-DECISIONS.md) | Numbered ADRs, adopted assumptions, risk register, genuine blockers and mitigations |
| [ERD.md](ERD.md) | Full database schema, RLS policies, entitlement-ledger invariants, retention columns |
| [API-SPEC.md](API-SPEC.md) | Endpoint contracts, error model, idempotency, rate limits, webhook and admin surfaces |
| [QUEUE-AND-JOB-SPEC.md](QUEUE-AND-JOB-SPEC.md) | Queue topology, message schema, state machine, checkpoints, budgets, retries, recovery |
| [AGENT-PROMPT-SPEC.md](AGENT-PROMPT-SPEC.md) | The twelve typed pipeline stages, structured output schemas, model routing, entity-resolution algorithm, length controller, quality gates |
| [SECURITY-THREAT-MODEL.md](SECURITY-THREAT-MODEL.md) | Data classes, threats and controls (SSRF, prompt injection, RLS/IDOR, letterhead, webhooks), provider privacy, retention jobs, incident response |
| [DEPLOYMENT-SPEC.md](DEPLOYMENT-SPEC.md) | Local demo mode, Hostinger KVM 2 deployment, environment variables, backups, observability, AWS Mumbai migration |
| [TEST-PLAN.md](TEST-PLAN.md) | Test strategy, acceptance tests (`AT-*`), golden cases (`GC-*`), end-to-end slices (`E2E-*`), security tests (`SEC-*`), CI stages |
| [REQUIREMENTS-TRACEABILITY.md](REQUIREMENTS-TRACEABILITY.md) | Every requirement ID mapped to component, database/API surface, acceptance test and status |
| [BUILD-CHECKLIST.md](BUILD-CHECKLIST.md) | Dependency-safe implementation checklist, phase gates, vertical slices |

## Reading order

1. SYSTEM-SPEC — what is being built and out of which parts.
2. ARCHITECTURE-DECISIONS — why it is shaped that way; what is assumed and blocked.
3. ERD → API-SPEC → QUEUE-AND-JOB-SPEC — the data and control plane.
4. AGENT-PROMPT-SPEC — the research pipeline that produces a Mandate Brief.
5. SECURITY-THREAT-MODEL → DEPLOYMENT-SPEC — how it is protected and operated.
6. TEST-PLAN → REQUIREMENTS-TRACEABILITY → BUILD-CHECKLIST — how completion is proven.

## Relationship to the product specification

`product-specification/` is authoritative for product behaviour. Where these implementation documents make a trade-off, they cite the governing conflict-precedence order from [`product-specification/README.md`](../../product-specification/README.md):

1. Security and legal boundaries
2. Entity-resolution protocol
3. Source and evidence policy
4. Product requirements
5. Mandate Brief specification
6. Research and agent architecture
7. Technical implementation preferences

Anything in this directory that goes beyond the product specification is explicitly labelled **[implementation addition]** and, where it embodies a choice, is backed by an ADR.

## Naming rules

- **Mandate** is the product; **Mandate Brief** is the flagship report. All user-facing copy uses these names.
- Internal/technical identifiers may use generic names (`reports`, `report_jobs`, `report_versions`) where that improves code clarity, per [doc 16](../../product-specification/docs/16-open-decisions-and-assumptions.md).

## Status legend

Used in REQUIREMENTS-TRACEABILITY.md and BUILD-CHECKLIST.md:

| Status | Meaning |
|---|---|
| `Specified` | Designed in this document set; no code exists |
| `In progress` | Being implemented on a feature branch |
| `Implemented` | Code merged; unit/integration tests pass |
| `Verified` | Acceptance test(s) pass end-to-end |
| `Blocked` | Cannot proceed; see blocker register in ARCHITECTURE-DECISIONS.md |
