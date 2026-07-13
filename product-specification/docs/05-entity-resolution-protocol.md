# 05 — Company Identity Resolution Protocol

## Purpose

Brands, websites and legal entities often differ. The contracting, operating, IP-owning, employing and holding entities may not be the same. Entity resolution therefore completes before paid research.

## Inputs

- website URL; or
- registered/legal name;
- optional CIN;
- optional state/country if ambiguity remains.

## Website discovery order

Inspect footer, contact page, privacy policy, terms, legal notice, cookie policy, investor relations, governance, annual reports/policies, careers/legal footers, consumer terms, GST/CIN/registered-office disclosures and structured metadata.

Extract “owned and operated by,” legal suffixes, CIN, GSTIN, office, copyright owner, controller/entity names and stock identifiers.

## Candidate generation

Sources include exact website names, name-to-CIN API, public search, exchange issuer pages, regulator records, company investor pages and credible providers.

Candidate record includes legal/former names, CIN, type/status, office/state, incorporation, domain linkage, directors/promoters where available, evidence, confidence and conflicts.

## Why CIN matters

Even without direct MCA document access, CIN uniquely identifies the company, prevents same-name mistakes, supports compatible master-data lookup, links provider records, improves director/charge/filing matching and creates an auditable entity key.

Mandate must never imply that CIN alone provides all MCA documents.

## Confidence model

| Factor | Weight |
|---|---:|
| Exact legal name and CIN on domain | 35 |
| Address/contact matches master data | 20 |
| Company-controlled legal page | 15 |
| Official regulator/exchange links domain | 15 |
| Directors/promoters/business match | 10 |
| Credible corroboration | 5 |

Negative factors include inactive status, conflicting office, incompatible business, name-only matches and common-name adverse results.

Labels: Strong match, Probable match, Ambiguous and Insufficient evidence. User confirmation remains mandatory.

## Brand rule

The Mandate Brief title and identity use the confirmed legal entity. Brand is contextual:

> [Legal Entity] operates the [Brand] business/website.

## Multi-entity decision

Include another entity only if it materially owns IP, employs staff, holds licences, owns assets/premises, contracts with customers, receives revenue, owns the brand/domain or controls the primary entity.

MVP:

- one primary entity;
- up to two material related entities in the same Mandate Brief;
- more complex groups require separate reports or a future group feature;
- supervisor proposes; user confirms.

## Listed-company handling

Resolve against legal issuer name, exchange symbol/code, issuer page, investor domain, CIN and registered office. Detect listed-parent/private-operating-subsidiary mismatches.

## Failure rules

- No match: ask legal name/CIN; no charge.
- Multiple matches: show evidence; do not guess.
- Inactive company: warn and ask about successor/former name.
- Inaccessible website: use legal name/search and record limitation.
- Foreign parent/Indian subsidiary: Indian entity is primary where the mandate concerns it.

## Acceptance tests

Include exact-CIN footer, privacy-policy-only name, brand/subsidiary, listed parent/private subsidiary, renamed company, similar names, inactive company, foreign parent, no legal disclosures, malicious page instructions and private-IP redirects.
