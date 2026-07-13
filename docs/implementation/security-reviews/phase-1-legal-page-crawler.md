# Phase 1 legal-page crawler security review

**Date:** 2026-07-13  
**Scope:** company-controlled legal-page discovery and deterministic disclosure extraction  
**Requirements/tests:** ENTITY-01, RUN-06 foundation, AT-ENTITY-01, ER-10/11, SEC-03/04

## Result

No open security deviation was found in the enabled HTML path. The crawler is a typed,
bounded consumer of SafeFetcher; it has no direct HTTP client, browser, model/provider,
credential, confidential-input or storage access.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| SSRF or redirect escape | Every read uses the injected SafeFetcher contract; only the submitted host and its `www` equivalent qualify as company-controlled; off-site redirects are discarded | SEC-03 SafeFetcher suite; ER-11 continuation test |
| Site restrictions | `robots.txt` is fetched first; unavailable, denied, off-site or invalid-media policy fails closed; disallowed paths and request-rate/crawl-delay rules are enforced | ENTITY-01 robots matrix |
| Paywall/CAPTCHA/access-control bypass | 401/403/407/429/451 and deterministic CAPTCHA/paywall signals produce stable limitations; no retry with credentials, browser impersonation or alternate route exists | ENTITY-01 access-control table |
| ToS automation restriction | An explicit automation prohibition stops subsequent domain access and is retained as a stable limitation | ENTITY-01 terms-stop test |
| Exhaustion | Sequential crawl; ≤15 page attempts, ≤100 candidates, ≤250 links/page, ≤2 MiB parseable HTML, ≤256 KiB robots policy, ≤5 s accepted crawl delay | ENTITY-01 hard-cap tests |
| Prompt injection/hostile markup | Scripts, iframes, templates, styles and hidden/ARIA-hidden markup are removed; suspicious instructions are flagged but never executed | SEC-04/ER-10 hidden-injection tests |
| False entity identifiers | CIN/GSTIN/ISIN/ticker patterns are bounded and deduplicated; ISIN checksum is validated; legal-name extraction is limited to labelled/standalone legal-suffix forms; LLP gets an explicit scope warning | AT-ENTITY-01 extraction tests |
| Excessive/copyrighted storage | Raw HTML is not returned; output retains a SHA-256, a ≤4,000-character excerpt and ≤1,000-character disclosure contexts for future Evidence records | Pydantic output constraints and tests |
| Auditability/failure states | Frozen extra-forbid Pydantic outputs carry crawler/extraction versions, robots state, page kind, canonical URL, content hash, attempt count and stable limitation/detail codes | model/config assertions |

## Security-precedence resolution: public PDFs

AGENT-PROMPT §3 asks site inspection to include annual-report/policy PDFs. The
higher-precedence product security rules require malware scanning and sandbox parsing of
untrusted files. The ADR-011 amendment therefore makes Phase 1 PDF handling fail closed:

- extension-identified PDF links are recorded but never fetched by the crawler;
- if an opaque URL returns `application/pdf`, SafeFetcher bounds the read and the crawler
  discards the body with `pdf_sandbox_pending`; and
- no pypdf/browser or unsandboxed fallback is introduced.

The later reusable scanner/sandbox must enable PDF inspection and add its hostile-file
tests before those documents can contribute entity evidence.

## AI definition of done

- **Schema/audit:** frozen typed outputs, stable versions/codes and content hashes.
- **Prompt/model/privacy route:** no prompt or model call; public company-controlled data
  only; identity, firm, billing and letterhead data are absent from the interface.
- **Timeout/retry/cost:** SafeFetcher supplies bounded network timeouts/retries; the
  crawler supplies crawl budgets and makes no paid call.
- **Failure/evaluation:** limitations are explicit and the 16-test crawler/extractor suite
  covers policy, extraction, injection and failure cases.

## Reproduction

```bash
uv run pytest -q services/worker/tests/test_legal_page_crawler.py
pnpm check
pnpm --filter @mandate/web build
```

Focused result: 16 crawler/extractor tests passed. Repository Python result at review
time: 106 tests passed; Ruff, formatting and strict mypy passed.
