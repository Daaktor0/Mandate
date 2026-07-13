# 10 — Security, Privacy and Legal Boundaries

This is a product/security specification, not a final legal compliance opinion. Applicable Indian and cross-border law must be reviewed before launch.

## Data classes

- **Public research data:** company website, public filings, regulator material, news, industry information, legal entity and CIN. May be sent to approved providers.
- **Account/billing data:** name, email, phone, OAuth IDs, payment, entitlements and support. Never send to research models.
- **User work product:** Mandate Brief edits, issues, user text and versions. No training without opt-in.
- **Firm branding:** letterhead/logo/background. Render-only; never sent to AI/search.
- **Prohibited MVP data:** confidential documents, data rooms, agreements, private cap tables, privileged communications, private mandate details and unnecessary personal data.

## OpenRouter/provider controls

Enforce Zero Data Retention per request, disable providers that train on submitted data, maintain an allowlist, log privacy routing, send only public research and generic role/context, exclude identity/billing/letterhead, redact unnecessary personal data, disable prompt logging and fail safely when approved capacity is unavailable.

## Authentication/authorisation

Google/Microsoft OAuth, secure cookies, RLS, signed short-lived storage links, separate admin role, least privilege, no service key in frontend and regular access review.

## Tenant isolation

User A must not list, fetch, edit, render, download or delete User B’s Mandate Brief. Signed links expire and report IDs alone do not authorise.

## Retrieval threats

- **Prompt injection:** retrieved text is untrusted; strip scripts and ignore behavioural instructions.
- **SSRF:** only HTTP/HTTPS; block private/reserved IPs and metadata; re-check DNS after redirects; cap redirects.
- **Malicious files:** allowlist types, size limits, malware scan, no executables/macros, sandbox parsing.
- **Exhaustion:** page/crawl/domain/browser/time and user-rate caps.

## Letterhead

Scan, strip active PDF content, sandbox rendering, encrypt in storage, retain briefly and delete temporary artifacts.

## Secrets and logging

Use environment/secrets manager, separate environments, rotation and redaction. Logs may contain IDs, stages, durations, providers, token/cost and redacted errors, but not OAuth tokens, payment credentials, full prompts by default, letterhead, user-added Mandate Brief text or secrets.

## Retention defaults

| Data | Default |
|---|---|
| Account/entitlement ledger | Account life plus legally required period |
| Mandate Briefs/versions | Until user deletes |
| Raw fetched page bodies | 30 days or less |
| Evidence metadata/excerpts | While Mandate Brief exists |
| Provider/model logs | 90 days |
| Security audit logs | 180 days, subject to review |
| Failed diagnostics | 30 days |
| Letterhead | After render or within 24 hours |
| Deleted report tombstone | Minimum billing/security record |

## Learning from edits

Separate consent, remove identity/branding, classify edit reason, human-review factual corrections, allow withdrawal for future training and maintain a curated private dataset.

## Product boundaries and incident response

State public information only, no legal advice/diligence, no completeness guarantee and independent verification required. Maintain incident ownership, severity, key revocation, notification, evidence preservation, provider contacts, backup recovery and post-incident review.

## Pre-launch tests

RLS/IDOR, SSRF, prompt injection, malicious file, webhook replay, entitlement races, dependency/container scans, secret scan, rate limits, deletion, backup restore and ZDR verification.
