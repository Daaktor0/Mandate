# Mandate

**Mandate** is an AI-assisted transaction-preparation product for corporate lawyers.

Its flagship output is the **Mandate Brief**: a concise, source-backed company and transaction-preparation report generated before a kickoff call.

The current product, research, technical, security, pricing and build specifications are maintained in [`product-specification/`](product-specification/README.md).

> Mandate prepares the transaction. A future integration may connect it with Closing Room for execution and closing.

## Implementation status

Implementation follows [`docs/implementation/BUILD-CHECKLIST.md`](docs/implementation/BUILD-CHECKLIST.md) in strict dependency order. Phase 0 and Gate G0 are complete. Phase 1 implementation is complete except for the blocked live 30-company master-data benchmark. Phase 2, the evidence pipeline, is in progress. No product behaviour should be treated as complete unless its checklist item and requirement-traceability status say so.

## Repository layout

- `apps/web/` — Next.js web app, route handlers and admin UI.
- `services/worker/` — Python worker, provider adapters, orchestration, fetching and rendering.
- `packages/shared-schemas/` — contract-first JSON Schemas and generated TypeScript/Python models.
- `supabase/` — migrations, local configuration and seed data.
- `fixtures/` — deterministic demo and golden-case inputs.
- `infra/` — Compose, Caddy and operational scripts.
- `docs/implementation/` — executable implementation specifications and checklist.
- `product-specification/` — authoritative product specifications.
