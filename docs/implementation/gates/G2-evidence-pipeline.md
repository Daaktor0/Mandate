# Gate G2 — Evidence pipeline

**Status:** Passed for the fixture-driven Phase 2 gate  
**Validated PR:** [PR #36](https://github.com/Daaktor0/Mandate/pull/36)  
**Requirements:** RUN-02, RUN-03, RUN-04, RUN-06, RUN-07, REPORT-06, REPORT-08, REPORT-09, REPORT-10, NFR-01

## Exit-gate evidence

| G2 condition | Evidence | Result |
|---|---|---|
| Evidence bundle is reviewable without prose | Evidence and Claim contracts carry identifier-only provenance; the stage-8 verifier emits approved claim IDs, evidence IDs, statuses, contradiction groups and coverage gaps. The persistence migration keeps evidence separate from prose and the web boundary cannot author verifier output. | Pass |
| Every claim carries type, evidence IDs, confidence and freshness | Shared claim schema and admission tests enforce claim type, evidence references, confidence and freshness; verifier tests cover scope, stale, duplicate, weak-source and prompt-suspect cases. | Pass |
| Checkpointed pipeline resumes safely | CheckpointedPipeline validates bounded canonical payloads and hashes, skips completed stages on redelivery, and the kill-and-resume test proves no completed stage is replayed. | Pass |
| GC-01..15 evaluation corpus is complete and safe | load_golden_cases loads exactly the 15 IDs, validates typed inputs/expectations, rejects missing IDs, reserved-host violations and sensitive/raw fields; seven focused tests pass. | Pass |
| Fixture mode is deterministic and zero-spend | Demo mode uses the SHA-256-pinned fixture catalog at revision 2026-07-17.2; the golden corpus itself has only synthetic identifiers and reserved hosts and cannot select a live provider. | Pass |

## Gate decision

All 13 Phase 2 checklist tasks are complete. The evidence pipeline has an
explicit admission boundary, typed research outputs, bounded prompt/model
transport, durable checkpoint semantics, deterministic contradiction/coverage
verification and the complete synthetic golden corpus. Phase 3 may begin at
the preliminary-research and clarification-planner task.

## Open items carried forward

- Phase 1 live benchmark remains blocked at 8/9 pending the B5 data-source decision.
- B3/B4 live-provider benchmark keys and vendor decisions remain open; demo-mode
  evidence does not substitute for live quality evidence.
- The Phase 3 lawyer review gate is human evidence and must not be self-certified.
