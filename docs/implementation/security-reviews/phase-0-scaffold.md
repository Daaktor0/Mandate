# Phase 0 scaffold threat-model review

**Status:** No open deviations after the hardening changes in this slice  
**Reviewed base:** `7a5f55bc95fe6c01efe4cc5845e4e944a6191583`  
**Authoritative model:** [SECURITY-THREAT-MODEL.md](../SECURITY-THREAT-MODEL.md)  
**Scope:** Phase 0 reachable code and configuration only

This review reconciles the implemented scaffold with the existing threat model. It
does not mark controls for later, unreachable product surfaces as implemented.

## Reconciliation

| Threat-model boundary | Phase 0 evidence | Disposition |
|---|---|---|
| Authentication and tenant isolation | The first migration forces RLS on `users_profile` and `report_requests`, has no user policies, revokes anonymous access and keeps `private.is_admin()` fail-closed. The local auth configuration disables email/password account creation; OAuth wiring remains Phase 5 work. | Conforms for the reachable foundation. |
| Public-information-only intake | `report_requests` has no document, upload or confidential-narrative column, requires `confidential_ack_at`, and authenticated writes are not yet exposed. The repository has no upload/data-room route. | Conforms; the Phase 1/3 API and answer-screening controls remain required before those inputs become reachable. |
| SSRF and hostile retrieval | `mandate_worker.fetch` has no implementation and the web app exposes no retrieval endpoint. | Not reachable. SafeFetcher and SEC-03 remain mandatory before Phase 1 retrieval work. |
| Prompt injection and model-provider privacy | `mandate_worker.gateway`, providers and agents have no implementation. Live mode has no silent fixture fallback; demo mode forces a complete synthetic, hash-validated zero-spend catalog. | Not reachable outside fixtures. The payload allowlist, ZDR enforcement and SEC-04/11 remain mandatory before the first real provider call. |
| Queue and worker trust boundary | `JobMessage` is identifier-only and forbids extra fields. Invalid messages are validated before handling; poison payloads are replaced by a hash-only dead-letter record; failures retry visibly. | Conforms. |
| Secrets and logging | CI scans full Git history with redacted Gitleaks output, audits locked dependencies and scans both images. Docker excludes credentials and Git history. The structured logger now recursively redacts secrets, identity, work product, prompts, raw content, exception detail and binary values at the sink while preserving approved audit metadata. | Conforms after SEC-09 hardening in this slice. |
| Malicious files and renderer | No letterhead/upload API exists. The renderer is non-root, read-only, capability-dropped, resource-bounded and has no network. | Conforms for the health-only renderer; file validation, scanning, rasterisation and SEC-05 remain required before letterhead support. |
| Payments, trials and cost amplification | Payment, webhook and trial-claim routes do not exist. `DEMO_MODE=1` cannot select paid adapters. | Not reachable. SEC-06/07/08/13 remain release-blocking when those surfaces are implemented. |
| Retention, deletion and legal-output controls | No report, evidence, letterhead, provider-log or payment storage exists and no Mandate Brief is composed yet. | Not reachable. The scheduled purge/reconciliation jobs and report disclaimers remain gated by their later phases. |

## Deviations found and closed

1. The structured logger previously trusted caller-supplied fields and had no
   sink-level redaction processor. `redact_sensitive_fields` and SEC-09 tests now
   enforce recursive redaction while retaining trace, provider, prompt-version,
   token-count, cost and duration metadata.
2. The generated local Supabase configuration previously allowed email/password
   account creation even though the product is OAuth-only. `[auth.email]` now has
   `enable_signup = false`, guarded by a SEC-01 foundation test.

No other Phase 0 deviation was found. Controls associated only with unimplemented
surfaces are explicitly deferred above; they are not treated as satisfied.

## Verification

- `pnpm check`
- CI stages 1–5, including the full-history secret scan, dependency/image scans,
  database integration tests and live container-boundary checks

