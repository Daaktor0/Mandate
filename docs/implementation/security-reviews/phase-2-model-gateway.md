# Phase 2 security review — ModelGateway

**Scope:** `services/worker/mandate_worker/providers/model_gateway.py`, the pinned model fixture, and focused gateway tests.

## Decision

Approved for the fixture-driven Phase 2 pipeline. Live OpenRouter use remains fail-closed until B3 supplies a reviewed route table, approved providers and transport credentials.

## Preserved boundaries

- Every model call enters through one typed `ModelGateway.complete` method.
- The task route fixes model id, prompt-bundle version, payload field allowlist, provider allowlist, token limits and call-cost limit.
- Payloads are rejected before routing when a top-level field is not task-allowlisted. Recursive inspection also rejects identity, firm, billing, payment, branding, confidential-matter, credential and secret keys nested inside an otherwise allowed field.
- The gateway accepts admitted public content and identifiers only. It has no direct access to user profiles, billing, letterhead storage, raw page bodies or quarantined binaries.
- Provider requests always carry `zdr=true` and an explicit provider allowlist. A response from a provider outside that allowlist raises `NoApprovedCapacity`; there is no permissive fallback.
- Structured output is validated against the supplied Pydantic schema. One repair request is permitted; a second invalid response stops with `model_output_schema_invalid`.
- Response token and cost metadata are checked against route and caller-supplied job budget limits before output is returned.
- `AgentRunRecord` contains only audit fields: report/job ids, task, model/provider, prompt version, token counts, cost, latency, ZDR status, repair status, success and stable error code. Prompts, payloads and provider output are not logged.
- `DEMO_MODE=1` selects the SHA-256-pinned fixture router and records zero tokens, zero cost and zero latency. Fixture selection outside demo mode and unknown/unconfigured live bindings fail closed.

## Tests

The focused suite covers deterministic zero-spend fixture calls, forbidden top-level and nested field injection, one-retry schema repair, terminal invalid output, response cost caps, non-allowlisted provider rejection, and fail-closed live configuration.

## Deferred dependencies

- Persisting `AgentRunRecord` to `agent_runs` is intentionally deferred to the next migration slice.
- A concrete OpenRouter HTTP transport and production routing table require B3. Adding credentials alone must not activate live routing.
- Evidence admission and untrusted prompt envelopes remain separate later Phase 2 tasks. The gateway cannot convert fetched or parsed content into Evidence.
