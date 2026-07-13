# Phase 1 SafeFetcher security review

**Date:** 2026-07-13  
**Scope:** `mandate_worker.fetch` policy, pinned transport and bounded fetch loop  
**Requirements/tests:** INTAKE-03, ADR-011, AT-INTAKE-03, SEC-03, ER-11 foundation

## Result

No open threat-model deviation was found in this slice. SafeFetcher is the only approved
worker boundary for outbound public-page HTTP(S) retrieval; later crawler and browser
code must depend on it rather than create a parallel client.

## Controls reviewed

| Threat | Structural control | Test evidence |
|---|---|---|
| Local, private, link-local, metadata, reserved, multicast and alternate-form IP targets | Canonical URL parsing plus `ipaddress` vetting; non-public host labels and integer-form hosts fail closed; IPv4-mapped, scoped, 6to4 and Teredo IPv6 forms are rejected | SEC-03 target table |
| Mixed or oversized DNS answer sets | One resolution result is deduplicated, capped and rejected in full if any answer is unsafe | SEC-03 mixed-answer test |
| DNS rebinding | Each request connects to the selected vetted IP; original hostname is used only for Host/SNI. Retries resolve and vet again | AT-INTAKE-03 pinning test; SEC-03 production transport and retry tests |
| Redirect pivot | Automatic redirects are disabled; each Location is canonicalised, resolved and vetted before the next request; maximum five redirects | ER-11 private redirect, same-host rebinding and redirect-budget tests |
| Proxy, cookie or credential leakage | Environment proxies are disabled, each hop uses an isolated client, no cookies/authentication headers are accepted, obvious credential-bearing URLs are rejected | SEC-03 production transport options and URL-policy tests |
| Decompression or response exhaustion | Only identity encoding and allowlisted content types are accepted; declared and streamed raw bytes are capped at 10 MiB; total/connect/read timeouts and attempts are bounded | SEC-03 response-policy, timeout and configuration-cap tests |
| Audit/log disclosure | Public result contains canonical request/final URLs, redirect chain, selected IP, status/content type and bounded body; failures expose stable codes rather than raw transport details | Typed result/error contracts and unit assertions |

## Deliberately deferred, not bypassed

- Robots/ToS handling, the per-domain and 15-page entity-resolution crawl limits and
  access-control/paywall/CAPTCHA stop decisions are part of the next legal-page crawler.
- Playwright interception through the same URL/IP policy is added only when browser
  retrieval becomes reachable.
- PDF malware scanning and sandbox parsing remain in their specified evidence and
  letterhead phases. SafeFetcher currently retrieves bounded allowlisted bytes only.

These items do not weaken the network boundary implemented here and must be completed
before their respective retrieval paths are enabled.

## Reproduction

```bash
uv run pytest -q services/worker/tests/test_safe_fetcher.py
pnpm check
pnpm --filter @mandate/web build
```

Focused result: 34 SafeFetcher tests passed. Repository result at review time: 29 web
tests, 4 shared-schema tests and 87 Python tests passed; lint, formatting, schema drift,
strict TypeScript/mypy and the production Next.js build passed.
