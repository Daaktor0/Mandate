# Web application

This directory owns the Mandate web application, short-lived API route handlers and the admin interface (SYSTEM-SPEC C1, C2 and C14).

Long-running research and rendering must never execute in the web request path. No service-role or worker/provider secret may be exposed to browser bundles.

The web app does not directly write the Phase 2 evidence, claims, checkpoint, agent-run
or provider-cost tables. Future API routes must use the authenticated owner boundary
or a narrowly scoped server-side operation; the migration currently leaves these
tables service-role-only until those policies and routes are reviewed. No browser
route may forward prompts, raw fetched bodies, letterhead, billing data or confidential
matter narrative to the worker or a provider.

Evidence admission remains a worker-side operation. The web application may later
request a research job after entity confirmation, but it must not accept a client-
supplied source tier, evidence object, prompt-injection flag or raw excerpt as
authoritative provenance.

Checkpointed progress is worker-owned. The web application may project completed
stage identifiers through a reviewed report-job API in a later queue slice, but it
cannot mark a stage complete, submit checkpoint payloads, or alter a retry attempt.

Verifier output is also worker-owned. The web app may display approved claim
statuses, disclosed conflicts and coverage gaps through a reviewed API later, but
it cannot resolve a contradiction, promote a rejected claim or mark a topic covered.

## Research-stage boundary

Research stages 2–7 are worker-owned. The web app may display typed progress
and later approved findings, but it must never submit claims, evidence IDs,
freshness metadata or source provenance as client-authored research output.
Evidence admission and `AgentFinding` validation remain server-side worker
boundaries.

The worker also owns prompt bundle versions and the mvp-standard research
budget ledger. The web application may show budget-aware progress or kickoff
questions later, but it cannot set caps, inject source text, or mark a budget
as exhausted on behalf of a client.
