# Phase 2 Evidence-pipeline persistence security review

**Date:** 17 July 2026
**Scope:** `report_jobs`, `job_checkpoints`, `evidence`, `claims`, `agent_runs` and `provider_cost_events` migrations
**Requirements/tests:** RUN-04, NFR-01, NFR-02, NFR-05, NFR-09, REPORT-06, REPORT-08, REPORT-09, SEC-11

## Result

The Phase 2 persistence foundation is present behind a forced-RLS, service-role-only
boundary. It stores job identity, resumable stage checkpoints, bounded source metadata,
normalised claims with evidence provenance, sanitised model-call audit records and
per-provider cost events. It does not admit fetched content, prompts or confidential
matter narrative; the later admission step remains a separate implementation task.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| Tenant or browser writes evidence | Every table has RLS enabled and forced; public, anon and authenticated table grants are revoked | `evidence_pipeline_persistence.test.sql` RLS assertions |
| Raw or confidential content persists | Columns are bounded and identifier-only; no prompt, raw-body, identity, billing, firm, letterhead or matter-narrative columns exist | `SEC-11` persistence-column assertion |
| Evidence is confused with prose | Evidence and claims are separate tables; material claims require evidence IDs and claim types/freshness/confidence are enums | `RUN-04` and `REPORT-06` pgTAP assertions |
| Claims cross job boundaries | A security-definer trigger verifies every referenced evidence ID belongs to the claim's job | Cross-job evidence-reference rejection |
| Resume duplicates a stage | Checkpoints have a unique `(job_id, stage, attempt)` key and bounded JSON payload/hash fields | `NFR-01` duplicate-checkpoint rejection |
| Model audit lacks ZDR proof or cost attribution | `agent_runs.zdr_enforced` must be true; token, latency, cost, routing and prompt versions are bounded; provider cost events require a job | `NFR-05`/`NFR-09` insert and rejection cases |

## Deliberate exclusions

- No user-facing read policy is added before the API contract is designed and reviewed.
- No fetched or parsed object becomes evidence merely because it can be inserted into
  the table; admission, source-tier classification and provenance construction are
  later Phase 2 slices.
- No live provider, parser, queue or model call is enabled by this migration.

## Verification

The intended clean-run checks are:

```bash
pnpm exec supabase db reset
pnpm exec supabase test db --local
pnpm exec supabase db lint --local --level error --fail-on error
```

The local workspace could not reach Docker Desktop's Supabase socket during this run;
the pgTAP reset/test and database lint therefore remain required CI checks before merge.
All non-Docker repository checks are run locally, and CI uses the clean Supabase stack.
