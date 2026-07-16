# Phase 2 security review — Corporate-filing integration

**Review date:** 2026-07-17  
**Scope:** runtime adapter selection, deterministic filing fixture and confirmation-gated acquisition service  
**Requirements/tests:** INTAKE-04/06, ENTITY-03/05, RUN-06/07, NFR-03/05, SEC-03/09

## Security conclusion

The corporate-filing boundary is now integrated into Mandate's fail-closed runtime plan without enabling direct MCA automation or binary parsing. Acquisition is reachable only through an identifier-only command whose state is literally `preliminary_research`, meaning the entity-confirmation step has completed. The provider receives only the confirmed CIN, selected filing types and optional financial years.

## Provider selection

- `DEMO_MODE=1` forces the validated `corporate_filings` fixture and makes zero network calls.
- Live mode may explicitly select `PROVIDER_CORPORATE_FILINGS=manual_mca_vpd`.
- Fixture selection outside demo mode fails closed.
- Unconfigured, unknown and advertised-but-unverified vendor names fail closed.
- No credential, API-key or environment-driven fallback selects a provider silently.

The manual MCA provider returns `human_action_required` and performs no login, payment, CAPTCHA, OTP, cookie replay or network request. A licensed provider remains unavailable until its provenance, licence, coverage, pricing and security terms are verified and separately implemented.

## Confirmation and privacy boundary

`ConfirmedCorporateFilingCommand` accepts only:

- report-request identifier;
- confirmed-entity identifier;
- the literal post-confirmation state `preliminary_research`; and
- the existing public, identifier-only `CorporateFilingRequest`.

Unknown fields are rejected. User identity, firm data, billing information, letterhead, confidential matter narrative, documents, passwords, OTPs and CAPTCHA material have no input field.

## Binary quarantine

The deterministic fixture is SHA-256 pinned by the demo manifest. Fixture documents are converted through the same `register_untrusted_corporate_filing` contract used for imported files. Every resulting reference is:

- size bounded;
- SHA-256 addressed;
- tied to the requested CIN;
- `pending_malware_scan`; and
- `parse_allowed=false`.

No document bytes are parsed, returned to a model, admitted as evidence or written to claims by this slice. The reusable malware-scan, archive-limit and sandbox-parser boundary remains the next dependency.

## Verification coverage

Focused tests cover:

- complete demo-adapter coverage and pinned fixture revision;
- fixture acquisition with scan-pending, non-parseable documents;
- rejection of identity fields and pre-confirmation state;
- manual MCA human-action behavior with zero provider calls; and
- fail-closed rejection of fixture and unverified vendor bindings in live mode.

Full linting, formatting, typechecking, secret/dependency/container scans, unit suites, database/container integration and requirements traceability must pass on the final PR head before merge.
