# 11 — Pricing, Payments and Refunds

## Pricing principle

Sell Mandate Brief entitlements, not “tokens.”

The founder’s proposed ₹1,499 for ten reports equals roughly ₹150 per Mandate Brief before payment fees, taxes, model/search costs, failures and support. That is unlikely to sustain a source-backed legal product.

Validate pricing after measuring at least 30 representative Mandate Briefs.

## Recommended launch pricing

- **Trial:** one free Mandate Brief for the first 100 eligible verified users; OAuth email + verified phone; one per person/device/risk cluster; same quality as paid reports.
- **Single:** ₹999; one entitlement; editing and PDF included; suggested 90-day validity; regeneration uses a new entitlement.
- **Practitioner pack:** ₹3,499 for 5 Mandate Briefs; 90-day validity.
- **Power pack:** ₹5,999 for 10 Mandate Briefs; 120-day validity.

Do not launch subscriptions until actual usage is known. Packs are simpler and fit irregular mandates. Tax/GST presentation requires accounting review.

## Entitlement accounting

1. Purchase grants credits.
2. Valid generation reserves one.
3. Quality completion consumes it.
4. Cancellation or terminal failure releases it.

Show reserved credits separately.

## Failure treatment

- Before entity confirmation: no reservation.
- Sparse information: disclose the likely limitation before reservation.
- Retryable failure: keep reserved while retrying within policy.
- Terminal failure: release immediately.
- Single purchase with no usable Mandate Brief: release and offer one-click refund; auto-initiate when service is clearly undeliverable.
- Pack failure: restore credit automatically.
- Quality complaint: admin may correct, restore, refund or reject abuse with recorded reason.

## Razorpay requirements

Server-created orders, server-fixed amount/package, browser success treated as provisional, verified webhook, idempotency, refund tracking, reconciliation, immutable gateway IDs and no card data stored.

## Trial abuse controls

OAuth, phone verification, IP velocity, CAPTCHA when risky, disposable-email blocking, one per phone, device/risk signals and manual blocklist. Avoid card requirement unless abuse becomes unmanageable.

## Unit economics

```text
Variable cost = model + search/extraction + company-data API + storage/PDF/email + payment fee + expected retry/failure + support allocation
```

Initial target: direct variable cost below 25–35% of net revenue, subject to actual data.

## Cost reduction

Entity confirmation, cheap extraction models, frontier synthesis only, caching, duplicate detection, stopping rules, model routing and later small-model extraction. Never reduce entity/provenance quality.

## Expiry and experiments

Suggested validity: single 90 days, 5-pack 90 days, 10-pack 120 days. Test ₹999 vs ₹1,499 single, pack sizes, premium reviewed tier and workspace plan. Do not use opaque or company-specific pricing.
