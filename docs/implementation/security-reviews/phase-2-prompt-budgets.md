# Phase 2 security review: prompt safety and research budgets

## Scope

This slice adds the model prompt boundary and the reusable job/stage budget
ledger. Checkpoint persistence, resume orchestration and the contradiction
verifier remain later Phase 2 slices.

## Controls

- `PromptEvidence` is a second allowlist over `EvidenceExcerpt`; source text is
  escaped and rendered only inside `<untrusted_source>` delimiters.
- The system frame states that source content is data, never instructions; it
  rejects role changes, secret/tool requests and scope changes, and requires a
  suspicion flag rather than obedience.
- Deterministic patterns flag common injection attempts. The flag is carried as
  envelope metadata and is not delegated to the model. No raw page, prompt,
  identity, firm, billing or letterhead field is added to the bundle.
- `BudgetProfile.mvp_standard` matches QUEUE §8 and validates that all stage
  slices fit inside job caps. `BudgetLedger` checks increments before commit,
  including search, page, model call, token, cost and wall-clock counters.
- Exhaustion has explicit outcomes: supported mandatory fields stop to bounded
  questions; transient inability maps to retry-wait; otherwise the job maps to
  restored failure. The ledger cannot expand a cap from caller input.

## Verification

`services/worker/tests/test_prompt_safety_budgets.py` covers delimiter escaping,
injection detection, forbidden-context exclusion, cap arithmetic, hard stops and
the three exhaustion decisions. The gateway and research-stage suites verify the
new prompt rendering and optional ledger wiring without provider spend.

## Residual risk

The ledger is request-local until the `job_checkpoints` persistence and
kill/resume slice lands. Live provider selection remains fail-closed and the
frontier-call counter is reserved for the later orchestration that selects that
tier.
