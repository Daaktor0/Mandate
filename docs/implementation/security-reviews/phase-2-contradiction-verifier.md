# Phase 2 security review — contradiction and coverage verifier

**Scope:** stage 8 claim verification, contradiction grouping, source ranking and coverage reporting.

The verifier consumes only job-scoped `Claim` contracts and admitted `Evidence`
metadata. It has no provider, HTTP, model-transport or raw-body access. Its output
is identifier-based and safe to checkpoint.

| Threat | Control | Evidence |
|---|---|---|
| A claim cites evidence from another job or entity | Request and evidence scope validators enforce job/entity ownership; unknown claim references are rejected | `test_REPORT_06_verification_request_rejects_cross_entity_evidence`; unknown-reference assertion |
| Duplicate or incompatible assertions are hidden | Exact duplicates are rejected; same-fact different assertions are grouped by deterministic UUID | `test_REPORT_06_verifier_rejects_duplicate_stale_and_suspicious_claims`; contradiction tests |
| Conflicting values are averaged into a false number | Common numeric units are normalised only for comparison; the verifier selects one ranked source or preserves an unresolved conflict | `test_REPORT_06_verifier_prefers_stronger_source_without_averaging`; `test_REPORT_06_verifier_preserves_tied_conflict_as_unresolved` |
| Weak, stale or injection-suspect material support reaches composition | Material claims with weak-only support become pending; stale or suspect-only support is rejected; approved IDs are emitted separately | `test_REPORT_06_verifier_rejects_duplicate_stale_and_suspicious_claims` |
| Missing research is presented as complete | Expected topics are compared with approved claim/evidence coverage and missing topics become explicit gaps | `test_REPORT_06_verifier_approves_supported_claim_and_reports_coverage` |
| Verifier leaks public-source text to persistence or the browser | Output contains claim/evidence IDs, statuses, reason codes and bounded coverage metadata only | `VerificationResult` schema; worker/web README boundaries |

Resolution is fail-closed: a tie in source strength and date becomes
`disclose_as_conflict`, while an unsupported or unresolvable assertion becomes a
gap/question candidate. The stage does not call providers, bypass the file-safety
boundary or override the evidence-admission step.
