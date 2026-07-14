# B5 — MCA master data and filing-document acquisition

**Status:** Architecture resolved; live vendors unselected  
**Verified:** 15 July 2026  
**Scope:** Company identity/master data and ROC/MCA source filings used by Mandate's public-information pipeline

## 1. Decision

Mandate must treat **company master data** and **source filing documents** as two different capabilities.

1. `CompanyDataProvider` resolves public identity fields such as legal name, CIN, status, incorporation date and registered office.
2. `SearchProvider` discovers public web sources. Exa is suitable for this layer; it is not an MCA registry source.
3. `CorporateFilingDocumentProvider` acquires source documents such as AOC-4, MGT-7, incorporation and charge filings.

The worker must not automate MCA login, payment, CAPTCHA solving or password/OTP handling. MCA credentials never enter Mandate.

## 2. Why direct MCA automation is rejected

MCA's View Public Documents service is an account-bound paid workflow rather than a public document API. Current MCA instructions state that:

- a successful transaction is limited to five documents for one company/LLP;
- paid documents are made available in the user's workspace for seven days;
- beginning a download starts a limited three-hour download window; and
- some downloads use an archive format that must be extracted locally.

MCA's published terms also state that its searchable databases are not intended for bulk downloads and that unusually high manual or automated access may be denied. Misuse of passwords or unauthorised access is prohibited.

Therefore Mandate will not use:

- Selenium/Playwright login automation against MCA;
- OCR or model-based CAPTCHA solving;
- shared MCA usernames, passwords or OTPs;
- replayed browser cookies;
- bulk scraping disguised as ordinary user activity; or
- unattended payment using a user's MCA account.

Official references:

- MCA View Public Documents: <https://www.mca.gov.in/content/mca/global/en/mca/document-related-services/view-public-documents-v3/download-documents.html>
- MCA Terms and Conditions: <https://www.mca.gov.in/content/mca/global/en/home/mca-mobile-app-policies/terms-and-conditions-of-use-.html>

## 3. Master-data sources

### 3.1 Open Government Data snapshot

The Government of India's Company Master Data catalogue is contributed by MCA and currently exposes a downloadable/API-backed dataset containing fields such as CIN, company name, status, class/category, capital, registration date, state and RoC.

Use case:

- broad offline identity lookup and candidate generation;
- deterministic snapshot versioning;
- freshness metadata shown to the resolver; and
- no claim that the snapshot is a live certified extract.

Reference: <https://www.data.gov.in/catalog/company-master-data>

### 3.2 Commercial master-data API

A commercial API may supplement the snapshot when its current documentation and contract prove:

- name and exact-CIN lookup;
- required fields and freshness;
- India availability;
- permitted storage, display and derived use;
- per-request pricing and limits;
- security and incident obligations; and
- no unsupported claim of direct MCA access.

Sandbox currently documents Company Master Data and Search Company endpoints. Probe42 also markets API-backed company information. Neither is selected until the exact contracted scope is verified.

References:

- Sandbox MCA APIs: <https://developer.sandbox.co.in/api-reference/kyc/mca/overview>
- Probe42 API portal: <https://apiportal.probe42.in/v1/>

### 3.3 Attestr correction

The repository previously treated Attestr as the selected name-to-CIN and master-data provider. Its current product catalogue does not establish the capability Mandate requires. The live Attestr selection is therefore disabled. The old adapter code is quarantined and must not be configured or treated as verified evidence.

## 4. Source filing acquisition

### 4.1 Preferred path — licensed filing provider

Use a licensed provider only after a procurement review confirms that its API can return the original or faithfully preserved MCA/ROC filing and that Mandate may store, parse, cite and display it.

Candidates for verification include:

- Probe42 source-document access; and
- Finanvo/Technowire's advertised credit-based document-order API.

Marketing claims are not sufficient. Before implementation, obtain and verify:

- endpoint documentation and sample responses;
- supported filing types and historical coverage;
- source-document provenance, SRN/filing date and original filename metadata;
- completeness and update latency;
- download URL expiry and retry semantics;
- malware handling;
- licence terms for storage, display and derived summaries;
- deletion/termination obligations;
- price per company/document; and
- support/SLA and security documentation.

Reference for the public Finanvo collection: <https://documenter.getpostman.com/view/14652297/TzXukeTe>

No vendor is selected by this spike.

### 4.2 Safe fallback — human-approved MCA VPD procurement

When no licensed API is configured, the pipeline may create a `human_action_required` acquisition task after entity confirmation.

An authorised Mandate operator then:

1. signs into MCA outside Mandate using their own authorised account;
2. selects only the required public filings;
3. approves and pays the MCA transaction;
4. downloads the documents within MCA's permitted window; and
5. imports them through an admin-only acquisition surface.

Mandate records only:

- confirmed CIN;
- requested and received filing type;
- financial year and filing date/SRN where available;
- MCA transaction/receipt reference without credentials;
- acquisition timestamp and method;
- source filename/media type;
- byte size and SHA-256; and
- scan/parser status.

It does not record the MCA password, OTP, CAPTCHA response, session cookie or payment instrument.

### 4.3 Consented target-company path

Sandbox EntityLocker may be considered only when an authorised representative of the target business authenticates and consents. This is not a general substitute for public-record retrieval and is unsuitable for ordinary third-party target research.

Reference: <https://developer.sandbox.co.in/api-reference/kyc/entitylocker/overview>

## 5. Security and parsing boundary

Every acquired filing is untrusted binary content.

The provider result may register metadata and a quarantined object reference, but the document remains:

- `pending_malware_scan`;
- `parse_allowed = false`; and
- inaccessible to model/search providers.

A later reusable file-safety stage must perform malware scanning, archive-bomb limits, format validation, sandboxed extraction and active-content stripping before any text is admitted to evidence. This preserves the existing ADR-011 PDF amendment.

Download URLs and vendor credentials must never be logged. Provider costs must be attributed to the report/job.

## 6. Pipeline behaviour

1. Entity resolution uses company-controlled pages plus master data and always requires user confirmation.
2. After confirmation, the research plan decides whether source filings are material.
3. The filing provider returns one of:
   - `ready` — quarantined source documents were acquired;
   - `human_action_required` — manual MCA VPD procurement is needed; or
   - `unavailable` — no licensed source or matching document exists.
4. Unavailable filings produce an explicit evidence gap. The system may continue using public sources but must not infer that a filing says something it has not inspected.
5. Listed-company research should first use issuer, BSE, NSE and SEBI publications, which often provide annual reports and disclosures without MCA procurement.

## 7. Acceptance criteria

The acquisition design is acceptable only when tests prove:

- no request or result field can carry a user identity, matter narrative, password, OTP, CAPTCHA or session cookie;
- manual MCA mode performs zero network/provider calls;
- a non-ready result cannot contain documents;
- a ready result cannot exist without document metadata;
- every document belongs to the confirmed CIN;
- every binary is SHA-256-addressed and scan-pending;
- parsing is structurally prohibited before the file-safety stage;
- source locators reject embedded credentials; and
- live provider selection fails closed until the provider is explicitly allowlisted and configured.

## 8. Current blocker state

- **B4 search:** Exa key is available; implement and benchmark Exa as `SearchProvider` in Phase 2.
- **B5 master data:** no live key; evaluate the OGD snapshot first and verify Sandbox/Probe42 only if live freshness is required.
- **B5 source filings:** no provider selected; retain fixture + manual VPD boundary while licensed vendor due diligence is performed.

The lack of a live provider does not block fixture-driven Phases 2–4. It does block claiming that the 30-company live Phase 1 benchmark or raw-MCA-document coverage is complete.
