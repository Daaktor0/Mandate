# 01 — Product Charter

## 1. Product and flagship output

**Mandate** is an AI-assisted transaction-preparation product for lawyers. Its flagship output is the **Mandate Brief**: an editable, source-backed briefing generated before a transaction kickoff call.

Mandate conducts structured public-information research, confirms the correct legal entity, analyses the business and regulatory context, and prepares a concise Mandate Brief and kickoff-call question set.

## 2. Problem statement

Preparation is currently fragmented across company websites, search engines, MCA-derived services, stock-exchange filings, regulatory websites, news, professional profiles and manually prepared questions. The work consumes lawyer time, varies by associate and is vulnerable to wrong-entity errors and generic AI summaries.

## 3. Target users

### MVP

- partners in corporate, M&A, PE, VC and general corporate teams;
- senior associates;
- associates and junior associates;
- individual lawyers purchasing reports directly.

### Later

- law-firm workspaces and knowledge teams;
- in-house legal teams;
- investment and diligence teams;
- Closing Room users if the products are integrated.

## 4. Brand architecture

- **Mandate:** the software product and platform.
- **Mandate Brief:** the flagship source-backed transaction-preparation report.
- **Possible future outputs:** Regulatory Brief, Counterparty Brief, Sector Brief and Matter Update.

The language in the product should be natural:

- “Create a Mandate Brief.”
- “Your Mandate Brief is ready.”
- “Open Mandate to review the brief.”

## 5. Positioning

**Chosen position:** transaction preparation tool.

Mandate must not be marketed as a replacement for due diligence, an AI lawyer, a legal opinion engine, a definitive corporate-record database or a confidential transaction workspace.

Suggested positioning:

> Mandate — public-information intelligence for better transaction kickoff calls.

Suggested tagline:

> Know the company before the first call.

## 6. Job to be done

> When I receive a new corporate mandate, help me enter the kickoff call with a verified understanding of the company, its business, sector, people, regulatory touchpoints, public-risk signals and the questions that matter for my side of the transaction.

## 7. Product principles

### Legal entity before analysis

A Mandate Brief about the wrong company is worse than no report. Substantive research begins only after explicit confirmation.

### Evidence before prose

Every material factual claim must map internally to evidence.

### Universal research, contextual interpretation

Research remains holistic. Client role and transaction context change priorities, matters for attention and questions—not the base fact collection.

### Questions are a core output

Questions must reflect what public research could not establish and what a lawyer needs to clarify.

### Concision is a feature

The main Mandate Brief defaults to two pages and is capped at four pages. Sources sit outside the main narrative.

### Visible uncertainty

The product distinguishes verified fact, company claim, third-party report, inference, conflict and unavailable information.

### Public information only

No confidential mandate descriptions or documents in the MVP.

### Human control

Users may edit, version and apply a letterhead. The system records AI-generated and user-added text separately.

## 8. Scope

### Included

- Indian private limited companies;
- Indian public unlisted companies;
- Indian listed companies;
- Indian and cross-border transaction contexts concerning them;
- foreign investors/acquirers as contextual entities.

### Deferred

- foreign companies as primary targets;
- LLPs, partnerships, trusts and funds as primary entities;
- individuals as primary subjects;
- unlimited group-wide diligence.

## 9. Outputs

A successful generation creates:

1. confirmed entity record;
2. structured research bundle;
3. editable Mandate Brief of one to four main pages;
4. mandatory kickoff questions;
5. source section/annex;
6. internal claim-to-source provenance;
7. downloadable PDF;
8. immutable system draft and versioned edits.

## 10. Non-goals

The MVP will not:

- claim complete access to MCA documents;
- issue final FEMA, FDI, labour or sectoral legal conclusions;
- certify exhaustive litigation searches;
- accept confidential uploads;
- generate a full diligence request list;
- manage closings;
- allow public sharing links;
- support firm workspaces;
- automatically train on every edit.

## 11. Success criteria

### Value

- download rate;
- repeat purchase;
- lawyer-reported time saved;
- Mandate Brief usefulness score;
- percentage of questions retained.

### Trust

- wrong-entity rate;
- unsupported-claim rate;
- citation coverage;
- stale-claim rate;
- issue rate;
- entitlement restoration rate.

### Operations

- successful completion rate;
- queue and generation duration;
- cost per successful Mandate Brief;
- provider error rate;
- payment reconciliation accuracy.

## 12. External launch gate

- entity confirmation works across a representative test set;
- material claims carry provenance;
- failed jobs restore entitlements;
- edits and PDF generation preserve versions;
- user identity and letterhead are excluded from model calls;
- users can delete Mandate Briefs;
- at least 30 lawyer-reviewed Mandate Briefs pass the evaluation rubric.
