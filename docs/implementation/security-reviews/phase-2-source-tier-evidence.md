# Phase 2 source-tier classification and evidence admission security review

**Date:** 17 July 2026  
**Scope:** `mandate_worker.evidence`, page-inspection conversion and the shared `Evidence` contract  
**Requirements/tests:** RUN-04, RUN-06, REPORT-06, REPORT-08, REPORT-09, NFR-09, SEC-04

## Result

The source-tier and evidence-object boundary is implemented as a deterministic,
service-side admission step. Page crawler output remains an
`UntrustedEvidenceCandidate` with `evidence_admitted=false`; only an explicit
`admit_evidence` call produces the shared `Evidence` object. Unknown sources fail
closed instead of being assigned a favourable tier.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| Unknown source presented as authoritative | Narrow authoritative host allowlist; all other tiers require an adapter-declared source kind | `test_REPORT_06_source_tiers_use_authority_allowlist_and_explicit_fallbacks` |
| Fetched page silently becomes evidence | Separate untrusted candidate type with a literal false admission flag; canonical object exists only after `admit_evidence` | `test_RUN_06_page_candidate_is_untrusted_until_explicit_admission` |
| Prompt injection disappears during admission | Suspicion flag is copied unchanged into the canonical object | `test_RUN_06_admission_preserves_prompt_injection_suspicion` |
| Provenance loses entity identifiers | Legal name, CIN and registered-office disclosures are bounded and copied into the shared identifier object | `test_RUN_06_page_candidate_is_untrusted_until_explicit_admission` |
| Source classification is ambiguous | Company-controlled pages map to tier 2; authoritative domains map to tier 1; unclassified public sources raise a stable error | `test_RUN_06_non_company_unknown_page_cannot_be_admitted_without_tier` |
| Unsafe metadata enters the object | Shared schema validation retains URL, hash, bounded excerpt, extraction method and retention class constraints | Focused six-test evidence suite |

## Deliberate exclusions

- This slice does not write to Supabase; the service-role-only `evidence` table
  remains the persistence target for the later research pipeline.
- It does not infer reputable publishers from names or search snippets. Such
  sources require an adapter classification before admission.
- It does not remove prompt-injection-suspected sources; it preserves the flag
  so the prompt/verifier stages can exclude them from model instructions and
  claim support.
- It does not parse binaries. Filing text remains behind the file-safety gate.

## Verification

```text
uv run ruff check services/worker/mandate_worker/evidence.py services/worker/tests/test_evidence_capture.py
uv run ruff format --check services/worker/mandate_worker/evidence.py services/worker/tests/test_evidence_capture.py
uv run pytest -q services/worker/tests/test_evidence_capture.py
```

All focused checks pass. Full repository checks and clean CI remain required
before merge.
