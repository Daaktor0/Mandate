# Phase 1 company-data and corporate-filing provider security review

**Date:** 2026-07-15  
**Scope:** generic company-data interface, deterministic fixture, Attestr quarantine, MCA/ROC filing acquisition boundary  
**Requirements/tests:** ENTITY-05, INTAKE-04, NFR-03/05, RUN-06, SEC-03/09

## Result

The earlier 13 July review incorrectly treated Attestr's live company-search/master-data
capability as verified. Current first-party product information did not establish the
capability Mandate requires. The vendor-specific conclusion is superseded by this review.

The generic `CompanyDataProvider`, fixture records and candidate-scoring boundary remain
valid. Worker startup now rejects `PROVIDER_COMPANY_DATA=attestr`; no alternative live
master-data provider is silently selected. B5 and the 30-company live gate remain open.

A separate `CorporateFilingDocumentProvider` now represents source filings. It deliberately
cannot automate MCA login, payment, CAPTCHA, OTP or cookies. Manual MCA VPD mode performs
zero network calls and emits a typed human-action state. Imported binaries remain
SHA-256-addressed, size-bounded, scan-pending and structurally unparseable.

## Controls reviewed

| Threat/boundary | Structural control | Test evidence |
|---|---|---|
| Identity/confidential data sent to a provider | Company-data methods accept only legal name/CIN; filing requests accept only CIN, filing types, financial years and a fixed public purpose; Pydantic rejects extras | INTAKE-04 provider/request allowlist tests |
| Unsupported vendor treated as production-ready | Worker boot fails when Attestr is selected in live mode; there is no replacement or fixture fallback | ENTITY-05 startup quarantine test |
| MCA credential/CAPTCHA automation | Manual VPD provider accepts no credentials and makes zero provider calls; only a stable `mca_vpd_login_payment_required` action is returned | RUN-06 manual-VPD test |
| False claim that filings were acquired | `ready` requires at least one document; non-ready states require an action code and cannot contain documents | RUN-06 result-invariant test |
| Wrong-company filing admitted | Every filing reference carries an exact validated CIN; result validation rejects a document whose CIN differs from the request | Corporate-filing model validation |
| Untrusted PDF/ZIP parsed directly | Registration always sets `pending_malware_scan` and `parse_allowed=false`; accepted media types and size are bounded | SEC-03 quarantine test |
| Secret-bearing locator logged or stored | Source locator rejects password/token/API-key/secret query material; provider secrets and signed URLs are outside the model | SEC-09 locator test |
| Fixture drift/unsupported source claims | Company fixture remains synthetic and SHA-256 pinned; filing fixture metadata identifies `fixture` acquisition | ENTITY-05 fixture and ADR-014 tests |
| Search evidence misrepresented as registry data | ADR-017 and vendor shortlist define Exa as public-web discovery only; master data and source filings use separate interfaces | Documentation/architecture review |

## MCA acquisition decision

Direct unattended MCA VPD automation is rejected. The permitted paths are:

1. a verified licensed document provider whose API, provenance and storage/display rights
   pass procurement review;
2. a human-approved MCA VPD purchase outside Mandate followed by admin-only import; or
3. a consented EntityLocker path when an authorised target representative participates.

No MCA username, password, OTP, CAPTCHA response, browser cookie or payment instrument is
stored in Mandate. See
[`B5-mca-data-and-document-acquisition.md`](../spikes/B5-mca-data-and-document-acquisition.md).

## AI definition of done

- **Schema/audit:** exact CIN, bounded filing request, explicit acquisition method/status,
  source provider/locator, acquisition time, SHA-256, size and quarantine state.
- **Prompt/privacy route:** no user identity, firm, billing, matter narrative or credentials
  can enter either provider request.
- **Timeout/retry/cost:** manual mode has zero external calls; future licensed providers
  must add bounded transport and report-attributed cost events before allowlisting.
- **Failure state:** unsupported Attestr configuration stops startup; unavailable filings
  produce a typed evidence gap/human action instead of fabricated content.
- **Evaluation hook:** fixture provider and invariant tests are deterministic; live master
  data and document providers remain blocked until their separate benchmarks pass.

## Deliberately deferred, not bypassed

- B5 live master-data source and ≥30-company accuracy test.
- Licensed source-filing vendor API/contract/provenance review.
- Admin acquisition UI, quarantine storage and malware/sandbox parser implementation.
- Any document text extraction or model use before the file-safety boundary is complete.
- Removal of the now-unreachable historical Attestr adapter code in a dedicated cleanup.

## Reproduction

```bash
uv run pytest -q \
  services/worker/tests/test_company_data_provider.py \
  services/worker/tests/test_corporate_filings_provider.py \
  services/worker/tests/test_demo_mode.py
pnpm check
pnpm --filter @mandate/web build
```

The final result must be taken from CI on this correction branch; no live provider or live
Supabase project is required.
