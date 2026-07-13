# Mandate

**Mandate** is an AI-assisted transaction-preparation product for corporate lawyers.

Its flagship output is the **Mandate Brief**: a concise, source-backed company and transaction-preparation report generated before a kickoff call.

The current product, research, technical, security, pricing and build specifications are maintained in [`product-specification/`](product-specification/README.md).

> Mandate prepares the transaction. A future integration may connect it with Closing Room for execution and closing.

## Implementation status

Implementation follows [`docs/implementation/BUILD-CHECKLIST.md`](docs/implementation/BUILD-CHECKLIST.md) in strict phase order. Phase 0 has started with the repository scaffold; no product behaviour is represented as complete until its checklist item and requirement traceability status say so.

## Repository layout

- `apps/web/` — Next.js web app, route handlers and admin UI.
- `services/worker/` — Python worker, provider adapters, orchestration, fetching and rendering.
- `packages/shared-schemas/` — contract-first JSON Schemas and generated TypeScript/Python models.
- `supabase/` — migrations, local configuration and seed data.
- `fixtures/` — deterministic demo and golden-case inputs.
- `infra/` — Compose, Caddy and operational scripts.
- `docs/implementation/` — executable implementation specifications and checklist.
- `product-specification/` — authoritative product specifications.
