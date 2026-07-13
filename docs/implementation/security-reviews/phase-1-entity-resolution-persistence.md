# Phase 1 entity-resolution persistence review

**Date:** 2026-07-13  
**Scope:** entities/candidates migration, request-state enforcement, resolution enqueue,
identifier-only outbox/queue, worker completion and terminal failure  
**Requirements/tests:** ENTITY-02/03/04/05, INTAKE-04/06, NFR-01/02/04, SEC-01

## Result

No open implementation deviation was found in this slice. Resolution is asynchronous,
tenant-scoped and unpaid. The web cannot write candidates or queue rows directly; the
worker cannot move a request across an illegal state edge. Successful work ends only at
`awaiting_entity_confirmation`, so paid research remains unreachable until the following
confirmation slice.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| Cross-tenant enqueue/read | Enqueue RPC derives `auth.uid()` and returns the same 404 signal for absent/other-owner requests; candidate SELECT joins through the owned request | SEC-01 route, adapter and pgTAP cases |
| Forged candidate or transition | Authenticated has SELECT-only entity/candidate grants; completion/failure functions are private/service-only; trigger rejects illegal state edges | SEC-01 privileges; ENTITY-03 transition test |
| Partial state/queue write | One RPC locks the request and commits state plus idempotent outbox row; replay is checked before state/rate limits | NFR-01 database replay/outbox tests |
| Identity/confidential data in queue | Generated `LightTaskMessage` and database CHECK permit exactly seven identifier/audit keys; route accepts no body | INTAKE-04 schema/route/pgTAP allowlist tests |
| Duplicate candidates on replay/cross-request collision | Candidate UUIDv5 includes request id; completion is one transaction and becomes a no-op after its terminal state | ENTITY-02 retry and completion-replay tests |
| Guessing/auto-confirmation | Persistence always stores `is_selected=false`; successful task stops at `awaiting_entity_confirmation` | ENTITY-03 state/payload assertions |
| Retry exhaustion stuck in resolving | Transient errors retain the queue lease for retry; terminal callback stores `failed_no_charge` and a stable code before DLQ | NFR-01 light-loop/failure RPC tests |
| Entitlement touched early | Migration, route command, task schema and worker repository have no ledger/reserve/consume surface | INTAKE-06 structural + DB assertions |
| Hidden reasoning retained | Candidate row stores versioned factor decisions, evidence ids and concise rationale codes only | ENTITY-02 score-audit constraints |

## AI definition of done

- **Schema/audit:** canonical light-task/response schemas; candidate payload alignment,
  factor audit, stable failure code and trace id persisted/propagated.
- **Prompt/privacy route:** no model call; provider/crawler receive only the typed public
  website/legal-name/CIN path; queue is identifier-only.
- **Timeout/retry/cost:** five-minute task timeout, four handled deliveries before DLQ,
  provider/generator call ceilings unchanged, and no API spend in demo mode.
- **Failure state:** no-match, deterministic failure and exhausted retry all end
  `failed_no_charge`; transient failures remain retryable without silent fallback.
- **Evaluation hook:** route/adapter, worker orchestration/loop, structural migration and
  39-case pgTAP suite; full ER-01..11 and B5 live accuracy remain ordered later tasks.

## Environment note

The workspace could not access its Docker socket, so the local pgTAP reset/lint command
could not run here. The migration has structural tests and its real Supabase reset,
39-case pgTAP file and database lint remain mandatory CI checks before merge.

## Deliberately deferred, not bypassed

- Candidate GET/confirmation/refine/related-entity UI and API (next checklist task).
- Full ER-01..11 orchestration and B5 30-company live staging gate.
- Full process supervisor/database-pool wiring and heavy-queue lifecycle (Phase 5).

## Reproduction

```bash
pnpm exec supabase db reset
pnpm exec supabase test db --local
pnpm exec supabase db lint --local --level error --fail-on error
pnpm check
pnpm --filter @mandate/web build
```
