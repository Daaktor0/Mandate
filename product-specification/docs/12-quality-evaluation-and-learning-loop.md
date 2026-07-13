# 12 — Quality Evaluation and Learning Loop

## Objective

Optimise Mandate Briefs for usefulness and trust, not fluency.

## Evaluation dimensions

- **Entity accuracy:** correct legal name/CIN, brand relationship and related entities. Wrong entity is an automatic failure.
- **Factual accuracy:** claims match sources; dates, figures, periods and entities are correct.
- **Provenance coverage:** 100% of material system claims internally linked to evidence.
- **Source quality:** appropriate tiers and authoritative sources where available.
- **Regulatory usefulness:** preliminary touchpoints without unsupported conclusions, including FEMA/FDI, labour, premises/factories, licences and sector questions where relevant.
- **Kickoff questions:** specific, non-duplicative, answerable, evidence-gap-linked and role-adapted.
- **Concision:** within page cap, no filler, high-value information first.
- **Freshness:** dynamic information within intended periods and stale claims labelled.
- **Public-risk matching:** correct entity/status and no common-name false positives.

## Automated gates

Entity consistency, evidence for material claims, no unsupported numerical claim, no unresolved high-severity conflict, 1–4 pages, question set/source annex/disclaimer present, no prohibited data and clean PDF rendering.

## Lawyer review rubric

Score 1–5 for entity correctness, business understanding, corporate/governance usefulness, industry/competitor usefulness, regulatory spotting, matters for attention, kickoff questions, sources, concision and overall preparedness.

Release target: no critical category below 3, average at least 4, zero wrong-entity reports and zero known unsupported material claims.

## Golden dataset

Include a simple startup, manufacturer, regulated fintech, health/pharma, consumer/food, SaaS/data, public unlisted group, listed company, brand/subsidiary mismatch, cross-border investor, sparse company, adverse false-positive, renamed company and multi-entity operation.

For each record the confirmed entity, must-find facts, expected touchpoints, unacceptable claims, must-ask questions and source expectations.

## Issue-to-root-cause map

| Issue | Root causes |
|---|---|
| Wrong entity | resolution |
| Inaccurate fact | extraction, stale source, synthesis |
| Weak source | source selection |
| Missing | coverage plan |
| Outdated | freshness |
| Poor question | role overlay |
| Formatting | renderer/editor |

## Learning from edits

Capture deletion, replacement, insertion, reorder, tone/length, source and question changes. Ask why meaningful edits occurred. Only reviewed factual/style signals enter datasets.

## Consent, experiments and monitoring

Use separate training consent, exclude identity/letterhead, allow withdrawal, keep lineage and human review. Evaluate model/prompt/search changes against the same golden set. Monitor wrong entity, issues per 100 Mandate Briefs, restorations, edits by section, source distribution, gate failures, cost, completion and question retention.

## Small-model readiness

Require several hundred approved examples, stable evaluation, consent/anonymisation, clear tasks, measured prompt baseline and licensing review.
