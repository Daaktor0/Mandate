# Phase 2 security review — PageFetcher boundary

**Review date:** 2026-07-15  
**Scope:** `mandate_worker.providers.page_fetcher`, provider exports and focused tests  
**Status:** implementation and focused tests complete; final full repository CI required

## Security conclusion

The PageFetcher slice preserves the existing ADR-011 outbound-network boundary and adds a
separate robots-aware extraction layer. It does not create `Evidence` or `Claim` records,
does not parse binary documents and does not provide any CAPTCHA, paywall, authentication
or automation-restriction bypass.

## Data minimisation

`PageFetchRequest` accepts one canonical public HTTP/HTTPS URL and rejects every additional
field. User identity, firm information, billing data, letterhead, prompts, answers and
confidential matter narrative therefore have no provider input surface. URL credentials,
non-default ports and credential-like query keys are rejected by the shared URL policy.

The response contains bounded extracted text, title, content type, canonical requested and
final URLs, redirect chain, SHA-256 digest, robots status, extraction version and an
injection-suspicion flag. Raw response bytes and the resolved connection address are not
exposed through the provider response.

## Network and SSRF boundary

Live retrieval is delegated exclusively to `SafeFetcher`. Consequently every robots and
page request inherits DNS answer-set vetting, public-unicast enforcement, IP pinning, Host
and TLS-SNI preservation, proxy/cookie isolation, redirect revalidation, decompression
disablement, response-size caps and bounded retry/timeouts. PageFetcher does not construct
an independent HTTP client.

The live builder allowlists only `safe_fetcher`. Fixture mode is available only through the
validated `DEMO_MODE=1` catalog; unknown and unconfigured bindings fail closed without a
credential-driven or fixture fallback.

## Robots and access controls

The adapter retrieves `robots.txt` before the requested page. Explicit denial, unavailable
robots policy, off-site robots redirect, unsupported robots content, excessive robots size
or a crawl delay above five seconds stops the operation. A published delay within the limit
is respected before page access.

CAPTCHA, paywall and explicit automation-restriction indicators return stable terminal
errors. No code attempts to log in, solve a challenge, replay cookies, use a headless browser
or weaken the access policy.

## Untrusted-content handling

HTML extraction removes scripts, styles, noscript/template content, SVG, iframes and hidden
or `aria-hidden` elements. Prompt-injection patterns are inspected against the raw bounded
source before those elements are removed, so suspicious instructions cannot disappear from
the audit signal merely because they are excluded from visible text.

Extracted content remains untrusted and carries `evidence_admitted=false`. This slice has no
route to a model, evidence table, claim table or report composer. A later evidence-admission
stage must classify the source, persist provenance and apply claim-level validation.

## Binary-document boundary

A PDF response fails with `page_binary_scan_required`. No PDF bytes are parsed, returned or
sent to a model. MCA/ROC filings and other imported PDF/ZIP assets remain under the separate
`CorporateFilingDocumentProvider` quarantine and require the reusable malware-scan and
sandbox-parser boundary before text extraction becomes reachable.

## Verification coverage

Focused tests cover:

- strict request-field and credential-bearing URL rejection;
- deterministic zero-network fixture behavior;
- robots-first ordering and crawl-delay enforcement;
- denial and unavailable-robots fail-closed behavior;
- hidden/script stripping with raw prompt-injection flagging;
- CAPTCHA, paywall and automation-restriction non-bypass;
- PDF scan gating;
- demo/live/unknown provider-selection rules; and
- explicit non-admission as evidence.

Full linting, typing, security scans, unit suites, ephemeral database/container integration
and requirements traceability must pass on the final branch head against the repaired pnpm
11 CI base before the PR is promoted or merged.
