# Supabase

Local configuration, database migrations and deterministic seed data live here. RLS is default-deny from the first migration; no migration may introduce an unprotected user-data table.

The CLI is pinned as a root development dependency. With Docker running:

```bash
pnpm exec supabase start
pnpm exec supabase db reset
pnpm exec supabase test db --local
pnpm exec supabase db lint --local --level error --fail-on error
```

The first migration creates `users_profile` and `report_requests`, forces RLS on both, and deliberately adds no user policies. `authenticated` has `SELECT` privilege so the zero-row default-deny behaviour is exercised rather than hidden by a table-level permission error. Later phase migrations add the minimum operation-specific policies alongside their APIs.

Phase 1 adds shared `entities`, owner-joined `entity_candidates` and a service-only
identifier-only `outbox`, all with forced RLS and explicit Data API grants. Resolution
starts through `enqueue_entity_resolution`; candidate completion/failure and outbox
dispatch are private worker-only functions. The request-state trigger rejects illegal
edges independently of the caller role.

Admin lookup is `private.is_admin()`, a fail-closed `SECURITY DEFINER` function in a non-exposed schema. `anon` has neither schema access nor function execution. Do not move privileged helpers into `public`.
