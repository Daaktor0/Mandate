# 02 — Product Requirements Document

Requirement IDs must be preserved in tickets, tests and pull requests.

## Authentication and account

- **AUTH-01:** Google OAuth login.
- **AUTH-02:** Microsoft/Outlook OAuth login.
- **AUTH-03:** Individual-user accounts in MVP.
- **AUTH-04:** Account shows purchased, reserved, consumed, restored and expired Mandate Brief entitlements.
- **AUTH-05:** User can delete account subject to mandatory billing/security retention.
- **AUTH-06:** Free trial eligibility uses email, verified phone, device and abuse signals.

## Intake

- **INTAKE-01:** Require only website URL or legal company name.
- **INTAKE-02:** Website helper text: “We will identify the legal entity behind this website and ask you to confirm it before research continues.”
- **INTAKE-03:** Reject localhost, private-network, malformed and unsupported URLs.
- **INTAKE-04:** Do not accept confidential free-form descriptions or documents.
- **INTAKE-05:** CIN is optional.
- **INTAKE-06:** No entitlement is reserved before entity confirmation.

## Entity resolution

- **ENTITY-01:** Inspect website legal pages and corporate disclosures.
- **ENTITY-02:** Generate candidate legal entities with supporting evidence.
- **ENTITY-03:** User confirmation is mandatory.
- **ENTITY-04:** If uncertain, ask for legal name/CIN.
- **ENTITY-05:** Store CIN as an exact identifier and use compatible master-data sources.
- **ENTITY-06:** Brand never replaces the legal entity in the Mandate Brief identity.
- **ENTITY-07:** Explain and confirm multi-entity scope.
- **ENTITY-08:** Label primary and related entities separately.

## Preliminary research and clarification

- **RESEARCH-01:** Conduct preliminary public research before contextual questions.
- **RESEARCH-02:** Ask only questions that materially affect interpretation or kickoff questions.
- **RESEARCH-03:** Mandatory clarifications cannot be skipped.
- **RESEARCH-04:** Client role is mandatory: company/promoter, investor/acquirer, seller/transferor, other.
- **RESEARCH-05:** Transaction type is optional and acts as an overlay, not a research limiter.
- **RESEARCH-06:** The system may ask whether foreign investment/counterparty is involved without soliciting confidential terms.
- **RESEARCH-07:** Explain why a mandatory question matters.

## Research execution

- **RUN-01:** Generation is asynchronous and queue-driven.
- **RUN-02:** Show truthful stage progress, not a long browser request.
- **RUN-03:** Use bounded business, industry, competitor, corporate, regulatory, public-risk and synthesis tasks.
- **RUN-04:** Store evidence separately from prose.
- **RUN-05:** Use structured model outputs where feasible.
- **RUN-06:** Treat fetched content as untrusted data.
- **RUN-07:** Enforce per-report search, page, token, time and retry budgets.
- **RUN-08:** Require entity, provenance, consistency, length and safety quality gates.
- **RUN-09:** Unrecoverable failure does not consume entitlement.
- **RUN-10:** Send completion/failure email.

## Mandate Brief

- **REPORT-01:** Standard two-page target.
- **REPORT-02:** Automatic one-to-four-page main brief.
- **REPORT-03:** Source annex excluded from page cap.
- **REPORT-04:** Kickoff questions mandatory.
- **REPORT-05:** Use “Matters for attention.”
- **REPORT-06:** Distinguish fact, company claim, third-party report, inference, conflict and unavailable information.
- **REPORT-07:** Avoid definitive legal conclusions.
- **REPORT-08:** Dynamic research focuses on three most recent completed financial years plus current period, or latest available periods.
- **REPORT-09:** Historical facts may extend to incorporation/founding.
- **REPORT-10:** Public-risk checks only where entity matching is reliable.

## Editing, letterhead and versions

- **EDIT-01:** Browser Mandate Brief editor.
- **EDIT-02:** System draft immutable.
- **EDIT-03:** Version or reconstructable diff on save.
- **EDIT-04:** Warn on unsupported user-added factual text.
- **EDIT-05:** Revert to earlier version.
- **EDIT-06:** Accept one-page PDF or image letterhead.
- **EDIT-07:** Never send letterhead to AI/search providers.
- **EDIT-08:** Preview letterhead-applied PDF.
- **EDIT-09:** Letterhead ephemeral by default.
- **EDIT-10:** Regeneration consumes a new entitlement; editing does not.

## History and issue reporting

- **HISTORY-01:** Dashboard lists entity, status, created and last edited.
- **HISTORY-02:** Reopen, edit, download or delete.
- **HISTORY-03:** No public share link.
- **ISSUE-01:** Categories: wrong entity, inaccurate fact, weak source, outdated, omission, formatting, other.
- **ISSUE-02:** Preserve Mandate Brief version and evidence references.
- **ISSUE-03:** Admin can restore entitlement and record root cause.
- **ISSUE-04:** Correction creates a new version.

## Payments

- **PAY-01:** Razorpay.
- **PAY-02:** Server-side verified webhooks are authoritative.
- **PAY-03:** Purchases create append-only entitlements.
- **PAY-04:** Valid job reserves entitlement.
- **PAY-05:** Final quality completion consumes it.
- **PAY-06:** Failure/cancellation releases reservation.
- **PAY-07:** Unrecoverable single-report failure triggers refund or restored entitlement under policy.
- **PAY-08:** Pack failures restore a credit.
- **PAY-09:** Webhooks idempotent.
- **PAY-10:** Refund and entitlement events auditable.

## Admin panel

Must show users, entitlements, jobs, queue, cost per Mandate Brief, retries, provider errors, sources, entity candidates, issue queue, refunds/restorations, trial abuse, prompt/model versions and health.

## Non-functional

- **NFR-01:** Jobs retryable and idempotent.
- **NFR-02:** Tenant isolation enforced at database layer.
- **NFR-03:** Containerised and Hostinger-independent worker.
- **NFR-04:** Trace ID across API, queue, model, search, payment and PDF.
- **NFR-05:** Every external cost attributable to a report.
- **NFR-06:** WCAG 2.1 AA target.
- **NFR-07:** Interactive requests remain short; research is asynchronous.
- **NFR-08:** Deletion follows retention policy.
- **NFR-09:** Store model IDs, prompt versions, parameters and evidence.
- **NFR-10:** Add workers without redesigning job state.

## MVP acceptance criteria

The build is accepted only if entity confirmation, durable queueing, claim provenance, entitlement restoration, versioned editing, safe letterhead rendering, reproducible PDF, tenant isolation and payment/provider cost reconciliation all pass end-to-end tests.
