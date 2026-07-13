# 06 — Source and Evidence Policy

## Purpose

A fluent Mandate Brief without defensible evidence is not a reliable legal work product. Evidence must exist before narrative.

## Source hierarchy

### Tier 1 — Authoritative

Government ministries/departments, lawful MCA-derived master data, stock exchanges, SEBI, RBI, DPIIT, CCI, sector regulators, courts/tribunals, gazettes, orders and filed annual reports.

Use for identity, status, formal filings and regulatory actions.

### Tier 2 — Company-controlled primary material

Company website, investor relations, official policies, press releases, product documents, management statements and official social accounts.

Label as company-stated unless independently verified.

### Tier 3 — Reputable independent material

Established news, recognised industry publications, research institutions, ratings agencies, investor portfolio pages and reputable professional-services publications.

### Tier 4 — Commercial aggregators/directories

Useful for discovery and corroboration. Verify material legal facts through stronger sources where feasible.

### Tier 5 — Social/user-generated

LinkedIn, X, YouTube, Reddit, forums and reviews. Use only where it materially helps and treat as a lead or attributed statement.

## Claim types

- `verified_fact`
- `company_claim`
- `third_party_report`
- `inference`
- `conflicted`
- `not_publicly_available`

Language must match strength. An allegation must never be presented as proven fact.

## Evidence object

Store URL/canonical URL, title/publisher, source tier, publication/access dates, relevant excerpt, content hash, entity identifiers, jurisdiction relevance, company-controlled flag, extraction method, prompt-injection suspicion and licence/terms notes.

## Claim provenance

Each material claim stores normalised subject/predicate/object, display text, claim type, evidence IDs, date/period, confidence, freshness, contradiction group, verifier status, Mandate Brief section and model/prompt version.

## Source presentation

Founder decision: sources only in the source section.

- no visible long URLs in the main narrative;
- group source entries by Mandate Brief section;
- web output includes clickable title/publisher/date;
- PDF uses numbered entries or concise links;
- claim-level provenance remains internal even when visible sources are grouped.

## Freshness

Historical information may extend to incorporation/founding. Dynamic information should prioritise the three most recent completed financial years plus current period, or the latest three available periods where filings lag.

The Mandate Brief states:

> Public-information research conducted up to [date/time].

## Conflicts

Prefer authoritative and later sources for the same fact, check definitions/periods, never average incompatible figures, preserve conflicts and explain them or convert them into kickoff questions.

## Adverse media and litigation

Include only where strong identifiers match: exact legal name/CIN, address, director/company context, industry/location, official party details or regulator/court record. Use cautious language and distinguish allegation, filing, order and final outcome. Never claim completeness.

## Prohibited retrieval behaviour

Mandate must not bypass paywalls/access controls or CAPTCHAs, impersonate a user, use user credentials, retrieve confidential/leaked documents, cite an AI answer as a source, rely only on snippets where the page is available, store excessive copyrighted text or scrape contrary to restrictions without review.

## Completeness rule

“No information found” means defined searches and authoritative-source checks were attempted with entity matching—not that one query returned nothing.
