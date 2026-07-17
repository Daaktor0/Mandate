# Phase 2 ModelGateway security review

**Date:** 17 July 2026  
**Scope:** typed `ModelGateway`, deterministic fixture implementation and OpenRouter live binding  
**Requirements/tests:** ADR-005, SEC-11, NFR-05, NFR-09

## Result

Mandate now has a single async model boundary behind `PROVIDER_MODEL=openrouter` for live
mode and the pinned fixture gateway in `DEMO_MODE=1`. The gateway resolves every task
through a versioned routing config, sends only the structurally allowlisted
`ModelTaskPayload`, enforces ZDR and provider allowlist parameters on every live request,
validates the caller's response schema and records an audit-safe `agent_runs` payload via
the configured sink.

The live binding is deliberately fail-closed. It requires `MODEL_ROUTING_CONFIG`,
`OPENROUTER_API_KEY`, a routed task, `zdr: required`, at least one allowed provider and
per-call/per-job cost capacity before any transport call can happen. The fixture binding
never constructs a transport and emits zero-token, zero-cost records.

## Deliberate exclusions

The gateway does not accept:

- user identity, firm, billing, letterhead, account, email or matter-narrative fields;
- confidential uploads or raw document bytes;
- arbitrary prompt text outside the versioned task payload;
- unrouted tasks or implicit default tiers;
- non-ZDR fallback providers; or
- provider fallback after an OpenRouter data-policy capacity refusal.

Fallback routes are accepted by the routing schema for future policy evolution, but this
slice uses only the primary route and never retries against a different provider list.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| Confidential data sent to a model | `ModelTaskPayload` has only task, prompt version, allowlisted identifiers, generic role and bounded admitted excerpts; unknown fields and identifier keys fail validation | SEC-11 payload allowlist tests |
| ZDR or provider allowlist omitted | Every OpenRouter request includes `provider.data_collection=deny`, `provider.zdr=true`, `provider.only=[...]` and `provider.allow_fallbacks=false` | SEC-11 transport-payload tests |
| Unrouted or unsafe model selection | `RoutingConfig.load` validates version, all tiers, route slug pattern, ZDR literal and non-empty provider allowlist; unknown tasks raise `model_task_unrouted` | SEC-11/NFR-09 routing tests |
| Schema drift or malformed output | Caller supplies the response model; one bounded repair retry is allowed, carrying only validation shape summary, not model output or payload text | NFR-09 schema-repair tests |
| Cost hidden or unbounded | Worst-case preflight checks block over-budget calls; actual token usage computes INR cost and is stored on the emitted run record | NFR-05 cost-cap tests |
| No ZDR capacity | OpenRouter no-endpoint data-policy signals map to `NoApprovedCapacity`; no alternate provider list or fallback call is attempted | Capacity tests |
| Fixture/live fallback | Fixture requires `DEMO_MODE=1`; live OpenRouter requires routing config and credentials; unconfigured/unknown providers fail closed | NFR-03 builder tests |
| Secret disclosure | OpenRouter API key is `repr=False`, never appears in models or logs and is supplied only as an authorization header to the fixed endpoint | SEC-09-style transport repr test |

## AI definition of done

- **Schema/audit:** validated payload, route, budget, structured response and
  `AgentRunRecord` with prompt version, model id, routing version, usage and cost.
- **Prompt/privacy route:** model messages are built only from the allowlisted payload;
  identity, billing, firm, letterhead and confidential narrative fields have no path into
  the gateway.
- **Timeout/retry/cost:** fixed endpoint, no proxies/redirects, bounded body, ZDR/provider
  params on every request, one repair retry and per-call/per-job caps.
- **Failure state:** missing config/key, unrouted task, unknown provider, no approved
  capacity, schema failure and cost-cap failure all emit stable machine codes.
- **Evaluation hook:** deterministic fixture tests run with zero spend; live vendor quality
  and slug pinning remain blocked pending B3.

## Deliberately deferred

- `agent_runs` database migration and durable sink.
- Provider-cost event persistence and report-level cost dashboard.
- Live vendor-slug pinning, staging quality benchmark and OpenRouter data-policy evidence.
- Prompt-bundle registry and full untrusted-envelope prompt architecture.
- Multi-route fallback policy, if later approved, with explicit ZDR-only constraints.

## Reproduction

```bash
uv run pytest -q services/worker/tests/test_model_gateway.py
pnpm lint
pnpm format:check
pnpm typecheck
```

No live OpenRouter call, API key or live Supabase project is needed for CI.
