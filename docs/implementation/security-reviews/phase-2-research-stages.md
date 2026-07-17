# Phase 2 security review: research stages 2–7

## Scope

This slice adds the bounded stage runner and typed `AgentFinding` output for
business, industry, competitors, corporate/governance, regulatory and
public-risk research. It does not add job budgets, persistence, checkpoints,
contradiction verification or report prose composition.

## Controls

- Each stage performs discovery through `SearchProvider`, fetches only through
  `PageFetcher`, and admits a page explicitly before any model call.
- The model payload contains only allowlisted identifiers and admitted bounded
  evidence excerpts. Tier-5 social/user-generated material is excluded from
  model input rather than promoted to a supported tier.
- Every material claim must reference an admitted evidence ID. Unknown evidence
  references and coverage-map references fail closed.
- Current/recent claims require a period inside the plan's current window;
  historical periods cannot precede the supplied incorporation floor.
- Competitor findings require a rationale and basis of competition. Regulatory
  findings require a confirmation question. Public-risk findings require a
  strong entity-match basis and proceeding status.
- Stage rationales and safeguards are retained as bounded `FindingNote` values,
  separate from claim prose. Hidden reasoning is neither requested nor stored.

## Exclusions and follow-up

The runner currently raises a stable error when no admissible evidence exists;
the later budget/checkpoint slice will turn bounded provider failures into
persisted gaps and resumable checkpoints. Live OpenRouter and Exa selection
remains fail-closed; fixture/test doubles exercise the contract without spend.

## Verification

`services/worker/tests/test_research_stages.py` covers all six stage mappings,
admitted-only model input, freshness windows, coverage provenance and
stage-specific fail-closed rules.
