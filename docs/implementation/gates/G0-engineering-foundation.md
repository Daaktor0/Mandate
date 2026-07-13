# Gate G0 — Engineering foundation

**Status:** Passed  
**Validated commit:** `828fc68418819b88f300f76bcab80815b6bcb182`  
**CI evidence:** [GitHub Actions run 29280214499](https://github.com/Daaktor0/Mandate/actions/runs/29280214499)  
**Requirements:** NFR-01, NFR-02, NFR-03, NFR-04, SEC-01, SEC-05, SEC-09, SEC-10, SEC-12, INTAKE-04

## Exit-gate evidence

| G0 condition | Evidence | Result |
|---|---|---|
| Reproducible staging-shaped deployment from Compose | CI Stage 5 starts a clean local Supabase stack, applies and resets the first migration, runs database tests and lint, then builds and starts the worker/renderer Compose stack with health, sandbox and portability probes. | Pass |
| Zero secrets in repository and images | CI Stage 2 runs checksum-verified Gitleaks over full Git history with redacted output, audits locked dependencies, and runs blocking Trivy vulnerability/secret scans against both production container targets. | Pass |
| Baseline tests green | CI Stages 1, 3 and 4 enforce formatting, lint, strict TypeScript/mypy, generated-schema drift checks, 6 Vitest tests and 53 pytest tests. | Pass |
| Requirements traceability enforced | CI Stage 7 regenerated evidence from all 59 JUnit cases, validated 85 requirement rows and linked `NFR-03` to two passing `AT-NFR-03` acceptance tests. | Pass |

## Gate decision

All eleven Phase 0 checklist tasks are complete. The foundation is dependency-pinned, fixture-capable, default-deny at the database boundary, container-portable, security-scanned and traceability-enforced. Phase 1 may begin at its first checklist task; no later-phase work is authorized early.

## Open items carried forward

- `NFR-01`, `NFR-02` and `NFR-04` remain `In progress`; their complete acceptance conditions depend on later phases.
- No Phase 0 blocker or threat-model deviation remains open.
- The exact next task is Phase 1 intake API and validation (`INTAKE-01..06`), including the SafeFetcher URL-policy boundary and confidential-information acknowledgement.
