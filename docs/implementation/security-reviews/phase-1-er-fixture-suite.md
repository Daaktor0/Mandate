# Phase 1 ER-01..11 fixture-suite security review

**Date:** 2026-07-14  
**Scope:** synthetic website/registry fixtures, entity-resolution acceptance harness, typed brand/group relationship hints  
**Requirements/tests:** ENTITY-01..07, INTAKE-04/06, RUN-06, SEC-03/04

## Review status

Implementation review is in progress and remains gated on the complete repository CI. The fixture corpus is synthetic, uses reserved `.example` domains, contains no credentials or live company data, and runs through the same bounded crawler and candidate generator used by the Phase 1 proof of concept.

## Controls reviewed

| Boundary | Control |
|---|---|
| Fixture provenance | Corpus declares itself synthetic and is rejected unless ER-01 through ER-11 are present exactly once and in order. |
| Network access | The harness supplies an in-memory fetch adapter; no fixture test performs live network access. |
| SSRF/private redirect | ER-11 injects the stable `non_public_ip_address` failure and requires resolution to continue through another public source with a recorded limitation. |
| Prompt injection | ER-10 hides malicious instructions in page markup and requires the suspicion flag without changing candidates or confidence. |
| Confidentiality | Fixture schema contains only public identity/evidence fields; a structural test rejects credential and confidential-matter vocabulary. |
| Brand/legal identity | Typed relationship hints attach brand context to a legal candidate; the legal name remains the candidate identity and the rendered statement follows the product-spec brand rule. Generated brand metadata is treated as optional at the schema boundary and handled fail-closed when absent. |
| Related-entity scope | A related reason must be tied to an identified candidate and a specific public evidence object. Conflicting materiality reasons fail closed. |
| Confidence integrity | Relationship hints are resolved after scoring facts are assembled, are excluded from every confidence factor and score-audit decision, and may add evidence/presentation metadata only. Acceptance tests compare candidate ids and scores with and without the relationship hints. |
| User confirmation | Every fixture outcome retains `requiresUserConfirmation=true`; the result schema has no auto-selection field. |
| Spend/entitlement | Fixtures use zero-call providers and do not expose entitlement, payment, or paid-research surfaces. |
| Supabase isolation | No live Supabase project is linked or referenced. Any later database stage runs only against GitHub Actions' ephemeral local Supabase/Postgres stack. |

## Deliberate boundary

The relationship hint is a typed internal public-evidence input. Automatic discovery of brand/group relationships from broader public-source research remains bounded by later retrieval adapters; this slice ensures that such evidence is represented and tested without introducing heuristic guesses or model-generated group structure.
