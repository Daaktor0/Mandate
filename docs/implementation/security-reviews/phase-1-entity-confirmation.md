# Phase 1 entity-confirmation security review

**Date:** 2026-07-14  
**Scope:** candidate read surface, confirmation/refinement RPC, related-entity scope, refinement queue handoff, and confirmation UI  
**Requirements/tests:** ENTITY-03, ENTITY-04, ENTITY-07, INTAKE-04, INTAKE-06, NFR-01, NFR-02, SEC-01

## Result

No open security deviation was found in the entity-confirmation slice. The user must make an explicit decision; no candidate is preselected or automatically confirmed. Confirmation and refinement remain tenant-scoped, idempotent where a key is supplied, and outside the entitlement lifecycle.

The original intake fields remain immutable in meaning: website and legal-name intake continue to be mutually exclusive. Later public-identifier refinements are stored in separate legal-name, CIN, and registered-office-state hint columns and are consumed only by the entity-resolution worker.

## Controls reviewed

| Threat or boundary | Structural control | Test evidence |
|---|---|---|
| Cross-tenant candidate access | Candidate reads traverse request ownership through RLS; absent and other-owner requests produce the same not-found result | SEC-01 route, repository, RLS, and pgTAP cases |
| Forged confirmation | The security-definer RPC derives `auth.uid()`, locks the owned request, verifies the candidate belongs to it, and rejects invalid states | ENTITY-03 API and database cases |
| Automatic or accidental confirmation | Candidate radios have no default selection; the database accepts only an explicit candidate id while awaiting confirmation | ENTITY-03 UI and pgTAP cases |
| Ambiguous identity | `none_of_these` removes stale candidates and returns to draft; `refine` accepts only bounded public identifiers and is permitted from draft, awaiting-confirmation, or failed-no-charge recovery states | ENTITY-04 UI, API, structural, worker, and pgTAP cases |
| Irrecoverable no-match loop | A failed or rejected candidate set can be retried; the guarded transition is `failed_no_charge → draft → resolving_entity`, while confirm/none actions remain restricted to awaiting confirmation | ENTITY-04 state-machine and pgTAP regression cases |
| Intake invariant erosion | Original website/legal-name fields are not rewritten; dedicated refinement hints preserve `report_requests_exactly_one_input` | NFR-02 foundation and ENTITY-04 migration cases |
| Stale refinement filters | Each refinement request replaces the prior hint set; omitted public identifiers clear obsolete hints rather than silently constraining later retries | ENTITY-04 migration structural cases |
| State hint ignored | The worker normalises the registered-office state and filters otherwise ambiguous provider results before scoring | ENTITY-04 worker unit case |
| Related-entity overreach | Scope is optional, unique, capped at two, excludes the primary entity, and accepts only entities explicitly proposed with a materiality reason | ENTITY-07 API and pgTAP cases |
| Duplicate side effects | Per-user/request advisory locking plus a private request/response replay ledger rejects key reuse with a different payload | NFR-01 API and pgTAP cases |
| Confidential content in queue | Refinement payloads contain only schema/task/request/user/attempt/trace identifiers; public identity hints remain in the tenant database | INTAKE-04 structural and pgTAP allowlist cases |
| Premature charging | The migration, RPC, web handler, and worker expose no entitlement reserve, consume, or ledger operation | INTAKE-06 structural, UI, and pgTAP cases |
| Enumeration and caching | Invalid UUIDs and cross-tenant misses return the same 404 shape; responses use `no-store` and `nosniff` | SEC-01 web cases |
| Abuse of refinement retries | Refinement is capped at ten resolution dispatches per user per hour and returns a stable 429 response | API and database rate-limit cases |

## AI and privacy definition of done

- **Prompt/data route:** no model invocation occurs in this slice. Only public website/legal-name/CIN/state identifiers reach entity-resolution adapters.
- **Schema/audit:** strict generated request/response contracts reject additional properties; candidate evidence and deterministic score audit remain separate from hidden reasoning.
- **Retry/cost:** refinement enqueues one identifier-only light task, uses the existing bounded resolution loop, and makes no paid research reachable.
- **Failure state:** none-of-these returns to draft; no-match/exhaustion remains `failed_no_charge`; both states permit a new public-identifier refinement, while malformed or stale decisions fail closed.
- **Deployment boundary:** tests use the ephemeral Supabase/Postgres stack in GitHub Actions. No Closing Room or other live Supabase project is referenced or modified.

## Deliberately deferred

- Producing `relatedEntityReason` from live multi-entity evidence remains part of the ordered ER fixture/live-validation work; this slice safely enforces and renders the scope when upstream evidence explicitly proposes it.
- Preliminary-research execution is Phase 3. Confirmation advances only to its state boundary and does not dispatch an unsupported worker task.
- B5 live-provider accuracy testing across at least 30 varied companies remains the final Phase 1 gate.

## Reproduction

```bash
pnpm check
pnpm test
pnpm exec supabase db start
pnpm exec supabase db reset
pnpm exec supabase test db --local
pnpm exec supabase db lint --local --level error --fail-on error
pnpm exec supabase stop --no-backup
```
