# 15 — Vendor and Data-Source Shortlist

**Verified:** 13 July 2026. Recheck pricing, terms, coverage and APIs before contracting.

## Pattern

No single API can responsibly gather “all internet information.” Use interchangeable layers: search, target-site crawler, company master data, official regulatory/exchange sources, optional legal database and model gateway.

## Search

- **Brave Search API:** broad web/news discovery. <https://brave.com/search/api/>
- **Tavily:** agent-oriented search/extraction. <https://www.tavily.com/pricing> and <https://docs.tavily.com/>
- **Exa:** semantic search and content retrieval. <https://exa.ai/> and <https://exa.ai/docs/>

Benchmark one primary provider on the golden set and retain a `SearchProvider` interface. Do not call all providers for every Mandate Brief.

## Website extraction

Start with bounded Playwright + Trafilatura/BeautifulSoup. Consider Firecrawl later if maintenance becomes burdensome: <https://www.firecrawl.dev/>

## Indian company data

- Probe42: <https://probe42.in/>
- Sandbox.co.in MCA APIs: <https://developer.sandbox.co.in/api-reference/kyc/mca/overview>
- Attestr name-to-CIN: <https://docs.attestr.com/attestr-docs/company-search-api-name-to-cin>
- Signzy KYB: <https://www.signzy.com/use-cases/know-your-business>
- Perfios/Karza: <https://perfios.ai/>

Recommendation: public website extraction plus one low-friction company search/master provider. Preserve adapters for enterprise vendors. Never describe vendor data as direct MCA access unless the contract/source supports it.

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

## First purchases

Use existing Hostinger, Supabase development/free tier, one search provider’s credits, a small OpenRouter balance and a company API trial. Defer litigation/enterprise contracts until Mandate Brief value is proven.
