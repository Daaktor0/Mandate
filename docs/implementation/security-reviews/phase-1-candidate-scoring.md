# Phase 1 candidate-generation and scoring review

**Date:** 2026-07-13  
**Scope:** candidate query planning, dedupe, evidence projection, deterministic confidence scoring and labels  
**Requirements/tests:** ENTITY-02/03/04/05, NFR-05, ER-01/02/05/06/07/09/10 foundations

## Result

No open implementation deviation was found in this slice. Candidate generation consumes
only the already-typed public site/company-data boundaries and typed public-source
signals. It emits the canonical generated `EntityCandidate` schema plus bounded scoring
audit metadata. It cannot confirm or auto-select an entity, enqueue paid research, reserve
an entitlement, call a model or write to storage.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| Weight/threshold drift | Six positive weights, five negative adjustments, zero floor and four thresholds are constants applied by one pure scorer | ENTITY-02 verbatim-weight and boundary tables |
| Non-deterministic or non-monotone ranking | Pure boolean factors; stable sort; exhaustive 2,048-combination property check; deterministic UUIDv5 candidate/evidence IDs | ENTITY-02 monotonicity/bounds and retry-ID assertions |
| Guessing among candidates | Result has literal `requiresUserConfirmation=true`, no selected-candidate field, and retains all bounded matches in score/name/CIN order | ER-06 structural assertion |
| Weak or hostile evidence changes score opaquely | Site factors use only stripped typed disclosures from company-controlled pages; prompt-injection suspicion does not alter scoring; external factors require typed candidate-scoped signals | ER-10 invariance and signal validation tests |
| Same-name/CIN confusion | CIN queries run first; CIN is exact/validated by the provider; records dedupe by CIN; master response mismatch already fails in the provider boundary | ENTITY-05 query-order/dedupe test |
| Address false positive | Match requires master-state agreement, ≥3 meaningful shared tokens and ≥0.5 overlap; automatic conflict requires a recognised state mismatch | ER-01 address-factor assertion; scorer audit |
| Unsupported source or entity claim | Provider provenance is allowlisted; unsupported company types and providers fail with stable codes rather than being mapped to a false private/public/listed claim | ENTITY-02 stable-failure test |
| Cost/query exhaustion | Sequential execution; ≤10 CIN queries, ≤10 name queries, ≤20 candidates, ≤20 evidence snippets/candidate and ≤40 provider calls including retries | NFR-05 hard-cap test |
| No-match entitlement risk | Empty result produces `legal_name_or_cin_required`; this layer has no entitlement, queue, database or billing dependency | ER-09 no-match test |

## Recorded scoring assumptions

These deterministic implementation choices fill details not fixed by doc 05 without
changing its weights or labels:

- `Pvt./Ltd.` punctuation and suffix abbreviations are normalised only for exact-name
  query dedupe/matching; the provider's current registered legal name remains the output.
- A former-name match earns the company-controlled-page factor but not the stricter
  “exact current legal name and CIN on domain” factor.
- The name-only penalty applies when a name search has no CIN lookup and no stronger
  domain/address/official/director/business/corroboration linkage.
- Provider records are CIN-bearing in this Phase 1 adapter; the later SearchProvider may
  add non-CIN leads, which must dedupe by normalised name+state before persistence.
- Regulator/exchange, director/business and corroboration factors enter only through
  typed candidate-scoped signals. The later retrieval adapters own signal classification;
  tier-1 is mandatory for official-domain links and tier ≤3 for credible corroboration.

## AI definition of done

- **Schema/audit:** canonical generated candidate schema; versioned factor audit, stable
  IDs, evidence IDs and rationale codes.
- **Prompt/privacy route:** no prompt/model call; public legal names, CINs, company fields,
  site disclosures and public source signals only.
- **Timeout/retry/cost:** provider owns timeout/retry; generator owns query/candidate/
  evidence ceilings and returns query/call counts.
- **Failure state:** stable unsupported-type/provider codes; no-match guidance; provider
  retryable errors propagate to the job layer without a fallback.
- **Evaluation hook:** 31 focused tests plus the future full ER-01..11 fixture gate and B5
  30-company live benchmark.

## Deliberately deferred, not bypassed

- `entities`/`entity_candidates` persistence and resolution state transitions (next task).
- Confirmation/refine/related-entity API and UI (following task).
- Full ER-01..11 fixture orchestration and the B5 live 30-company accuracy gate.
- Search/regulator/exchange adapters that produce additional typed signals.

## Reproduction

```bash
uv run pytest -q services/worker/tests/test_candidate_scoring.py
pnpm check
pnpm --filter @mandate/web build
```

Focused result: 31 candidate-generation/scoring tests passed; Ruff, formatting and strict
mypy passed.
