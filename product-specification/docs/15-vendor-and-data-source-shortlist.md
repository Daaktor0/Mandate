# 15 — Vendor and Data-Source Shortlist

**Verified:** 15 July 2026. Recheck pricing, terms, coverage and APIs before contracting.

## Pattern

No single API can responsibly gather “all internet information.” Use interchangeable layers: search, target-site crawler, company master data, official regulatory/exchange sources, optional legal database and model gateway.

## Search

- **Brave Search API:** broad web/news discovery. <https://brave.com/search/api/>
- **Tavily:** agent-oriented search/extraction. <https://www.tavily.com/pricing> and <https://docs.tavily.com/>
- **Exa:** semantic search and content retrieval. <https://exa.ai/> and <https://exa.ai/docs/>

The founder has an Exa key. Implement Exa behind `SearchProvider` and benchmark it on the golden set. Exa is a public-web discovery/content provider; it is not an MCA registry or source-filing provider.

## Website extraction

Start with bounded Playwright + Trafilatura/BeautifulSoup. Consider Firecrawl later if maintenance becomes burdensome: <https://www.firecrawl.dev/>

## Indian company master data

Master data and source filing documents are separate capabilities.

- **Government Open Data Company Master Data:** MCA-contributed snapshot/API catalogue for CIN, legal name, status, class/category, capital, registration date, state and RoC. <https://www.data.gov.in/catalog/company-master-data>
- **Sandbox.co.in MCA APIs:** current documentation covers Company Master Data and Search Company. <https://developer.sandbox.co.in/api-reference/kyc/mca/overview>
- **Probe42:** company-information and API platform; verify exact fields, freshness, pricing and licence before selection. <https://probe42.in/> and <https://apiportal.probe42.in/v1/>
- **Signzy KYB:** <https://www.signzy.com/use-cases/know-your-business>
- **Perfios/Karza:** <https://perfios.ai/>

The earlier Attestr recommendation is withdrawn: its current product catalogue does not establish the legal-name/CIN company-master-data capability Mandate requires. Do not configure or procure it for this purpose.

Recommendation: start with the versioned Government Open Data snapshot for broad identity resolution, then add one verified live master-data API only if the 30-company benchmark shows freshness/coverage requires it. Never describe vendor data as direct MCA access unless the contract and source provenance support that statement.

## MCA/ROC source filing documents

The MCA View Public Documents service requires login, payment and a limited download workflow. Mandate must not automate MCA login, CAPTCHA, OTP or payment.

Use a separate `CorporateFilingDocumentProvider` with:

1. a fixture implementation for demo/CI;
2. a licensed source-document vendor after API and licence verification; and
3. a human-approved MCA VPD procurement fallback that imports documents into quarantine without storing credentials.

Candidates requiring procurement verification:

- **Probe42 source documents:** public material advertises one-click source-document access, but raw-document API scope must be confirmed.
- **Finanvo/Technowire Documents V3:** public material describes credit-based CIN order/list/download/ZIP APIs. Verify provenance, coverage, storage/display rights, pricing and security before implementation. <https://documenter.getpostman.com/view/14652297/TzXukeTe>

Detailed decision: [B5 MCA data and document acquisition](../../docs/implementation/spikes/B5-mca-data-and-document-acquisition.md).

## Listed companies

Use BSE, NSE, SEBI, issuer investor-relations, annual reports and shareholding patterns:

- <https://www.bseindia.com/>
- <https://www.nseindia.com/>
- <https://www.sebi.gov.in/>

## Regulatory

Use official RBI, DPIIT/Startup India, CCI, IRDAI, PFRDA, TRAI/DoT, CDSCO, FSSAI, pollution-control, ministries, state regulators and labour departments depending on business classification.

## Litigation/public risk

Use official courts/tribunals, eCourts, NCLT/NCLAT, regulator orders, IBBI and credible legal news. Commercial possibilities include SCC Online, Manupatra, LexisNexis and vendor legal-history data. Confirm API licence, display rights, entity fields, retention and price. Do not assume unrestricted commercial automation of public legal sites.

## Supabase

Google/Microsoft auth, Postgres, RLS, Storage and Queues:

- <https://supabase.com/docs/guides/auth>
- <https://supabase.com/docs/guides/auth/social-login/auth-google>
- <https://supabase.com/docs/guides/auth/social-login/auth-azure>
- <https://supabase.com/docs/guides/queues>
- <https://supabase.com/docs/guides/database/postgres/row-level-security>

## OpenRouter

Unified models, fallback, cost reporting and ZDR:

- <https://openrouter.ai/docs/quickstart>
- <https://openrouter.ai/docs/guides/features/zdr>
- <https://openrouter.ai/docs/guides/privacy/provider-logging>
- <https://openrouter.ai/docs/guides/routing/provider-selection>
- <https://openrouter.ai/pricing>

Enforce ZDR, provider allowlist and no account/firm data.

## Razorpay and hosting

Razorpay: <https://razorpay.com/payment-gateway/>, <https://razorpay.com/pricing/>, <https://razorpay.com/docs/>.

Hostinger KVM 2 public specification: 2 vCPU, 8 GB RAM, 100 GB NVMe and 8 TB bandwidth; suitable for a bounded early worker, not frontier inference. <https://www.hostinger.com/in/vps-hosting>

## Procurement checklist

Data sources, freshness, coverage, identifiers, limits, India availability, location, retention/training, SLA, per-report cost, display/storage/training rights, termination/export, security, subprocessors and incident notice.

For source documents, additionally verify original-file provenance, filing type/date/SRN metadata, historical completeness, download expiry, malware handling and the right to retain/cite the original filing.

## First purchases

Use existing Hostinger, Supabase development/free tier, the available Exa credits, a small OpenRouter balance and—only after verification—one company master-data or filing-document trial. Defer litigation/enterprise contracts until Mandate Brief value is proven.
