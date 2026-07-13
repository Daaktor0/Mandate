# Phase 1 CompanyDataProvider security review

**Date:** 2026-07-13  
**Scope:** company-data interface, deterministic fixture, Attestr v2 adapter and runtime selection  
**Requirements/tests:** ENTITY-05, INTAKE-04, NFR-03/05, RUN-06 foundation, AT-ENTITY-05

## Result

No open implementation deviation was found in this slice. The provider can receive only
a public legal name or exact CIN. Demo mode is deterministic and zero-spend; live mode
fails closed when the selected adapter or credential is unavailable. Blocker B5 remains
open because provider credentials, commercial/data-use review and the varied 30-company
staging accuracy test are external gate dependencies.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| Identity/confidential data sent to a vendor | Interface methods accept only a legal-name string or CIN; request bodies have hard-coded keys; master lookup disables charges/e-filings | INTAKE-04 payload allowlist test |
| Excess provider data retained | Attestr responses are parsed through allowlisted models; directors/signatories, email, filings, charges, capital and raw bodies are discarded | ENTITY-05 bounded-field test |
| Wrong-company acceptance | CIN is uppercased and validated against the exact Indian company identifier shape before I/O; master response registration ID must equal the requested CIN | ENTITY-05 invalid/mismatch tests |
| Secret or vendor-body disclosure | Auth token is a repr-hidden transport field; stable errors include only a code and retryability; raw error bodies are never surfaced | RUN-06 auth-failure test |
| Endpoint/proxy/redirect abuse | Transport selects between two compile-time Attestr v2 HTTPS URLs, disables environment proxies and redirects, requests identity encoding and accepts JSON only | INTAKE-04 transport test |
| Spend/retry exhaustion | ≤20 results, ≤2 calls per operation including retries, ≤8-second request timeout and ≤1 MiB streamed response; response records include call count for later cost events | NFR-05 call-cap tests |
| Silent unsafe fallback | Fixture construction requires a loaded demo plan; unconfigured, unknown and credential-less live providers fail closed | NFR-03 selection test |
| Fixture drift/unsupported source claims | Fixture payload is synthetic, schema-validated and SHA-256 pinned; its notice explicitly disclaims MCA/legal-database provenance | ENTITY-05 fixture tests; ADR-014 catalog tests |

## AI definition of done

- **Schema/audit:** frozen Pydantic records/results; exact CIN; operation, provider,
  fixture flag and bounded call count retained.
- **Prompt/privacy route:** no model or prompt; only public legal name/CIN can enter;
  allowlisted public master-data fields can leave.
- **Timeout/retry/cost:** eight-second transport timeout, two-call retry ceiling, result
  and response-size caps; zero calls in demo mode.
- **Failure state:** stable retryable/non-retryable codes; no fixture fallback in live
  mode; malformed/mismatched responses rejected.
- **Evaluation hook:** tagged provider contract tests and deterministic fixture feed the
  candidate scorer and ER suite in the next checklist slice.

## Deliberately deferred, not bypassed

- B5 live credentials and provider contract/data-use review.
- The ≥30-company varied staging accuracy test and any provider-specific calibration.
- `entities`/`entity_candidates` persistence, confidence scoring and report-attributed
  `provider_cost_events`, which remain in their ordered Phase 1/2 tasks.

## Reproduction

```bash
uv run pytest -q services/worker/tests/test_company_data_provider.py services/worker/tests/test_demo_mode.py
pnpm check
pnpm --filter @mandate/web build
```

Focused result: 19 provider/demo tests passed; Ruff, formatting and strict mypy passed.
