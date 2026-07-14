# Phase 2 Exa search-provider security review

**Date:** 15 July 2026  
**Scope:** typed `SearchProvider`, deterministic fixture implementation and Exa live adapter  
**Requirements/tests:** INTAKE-04, RUN-06, RUN-07, NFR-03/05, SEC-03/09

## Result

Mandate now has a generic public-web search boundary and a live Exa implementation behind
`PROVIDER_SEARCH=exa`. The adapter is discovery-only: a result URL or highlight is not an
`Evidence` object and cannot support a claim until Mandate independently retrieves the URL
through `SafeFetcher`, captures provenance and passes the later evidence-classification
pipeline.

The implementation follows Exa's current first-party Search API contract:

- fixed `POST https://api.exa.ai/search` endpoint;
- `x-api-key` authentication;
- bounded `numResults`;
- extractive `contents.highlights` retrieval;
- per-result title, URL, source id, publication date, author and highlights; and
- reported `costDollars.total` retained for later report-level cost attribution.

Official references:

- <https://exa.ai/docs/reference/search>
- <https://exa.ai/docs/reference/contents-retrieval>

## Deliberate exclusions

The adapter does not request:

- Exa summaries or structured summaries, which are model-generated rather than source text;
- full-page text, which belongs behind Mandate's own fetch/extraction and provenance controls;
- deprecated combined `context` output;
- subpage crawling, image extraction or synthesized output;
- user identity, firm, billing, letterhead or document fields; or
- company-master-data or MCA-filing treatment.

Exa remains `SearchProvider`; it is not `CompanyDataProvider` or
`CorporateFilingDocumentProvider`.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| Confidential/account data sent to search | `SearchRequest` has only query, bounded result count, domain filters and publication-date filters; unknown fields fail validation | INTAKE-04 request allowlist test |
| Search provider bypasses retrieval controls | Results are typed discovery metadata only; URLs are not fetched by Exa adapter and remain subject to `SafeFetcher` | RUN-06 boundary review |
| Provider-generated summary presented as evidence | Payload requests extractive highlights only; tests reject the presence of `summary`, full `text` or deprecated `context` | RUN-06 payload test |
| Unbounded spend or result volume | Limit 1–20, at most two provider calls, 2 MiB response cap, 10 s timeout, reported cost bounded and retained | RUN-07 bounds/retry tests |
| Secret disclosure | API key is `repr=False`, never appears in request/result models and is supplied only as `x-api-key` to the fixed endpoint | SEC-09 repr/config tests |
| Proxy/redirect abuse | `httpx.AsyncClient` uses `trust_env=False`, `follow_redirects=False`, fixed Exa URL and identity encoding | Transport implementation review |
| Malformed or credential-bearing result URL | HTTP/HTTPS only, hostname required, credentials and non-default ports rejected, fragments stripped, duplicate canonical URLs removed | SEC-03 response tests |
| Silent fixture/live fallback | Fixture requires `DEMO_MODE=1`; live Exa requires `EXA_API_KEY`; unconfigured/unknown providers fail closed | NFR-03 builder tests |
| Retry amplification | Only transport failures, 429 and 5xx may retry once; invalid request/auth/response failures do not retry | RUN-07 retry classification tests |
| Search cost hidden | `costDollars.total` is stored as `cost_usd` with provider-call count for later `provider_cost_events` integration | NFR-05 response test |

## AI definition of done

- **Schema/audit:** validated request, provider, fixture flag, call count, reported cost and
  bounded typed results.
- **Prompt/privacy route:** no user/account/billing/letterhead/document fields exist in the
  provider request; search output is marked untrusted discovery material.
- **Timeout/retry/cost:** fixed endpoint, no proxies/redirects, bounded body/time/calls/results,
  stable retry classifications and cost metadata.
- **Failure state:** missing key, unconfigured/unknown provider, invalid media type/body and
  unsafe URLs fail closed with stable codes.
- **Evaluation hook:** deterministic fixture tests run with zero spend; the live golden-set
  quality/cost benchmark remains B4 and requires the founder's Exa key in staging only.

## Deliberately deferred

- `PageFetcher` adapter and evidence-object persistence.
- Provider-cost event database writes tied to a report job.
- Live Exa benchmark against the golden set and search-query templates.
- Search-budget orchestration across the complete research pipeline.
- Search-result source-tier classification and contradiction checks.

## Reproduction

```bash
uv run pytest -q services/worker/tests/test_search_provider.py
pnpm check
pnpm --filter @mandate/web build
```

No live Exa call, API key or live Supabase project is needed for CI.
