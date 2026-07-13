# TEST-PLAN — Mandate MVP

**Status:** Specified
**Sources:** product-specification docs 13 (testing), 12 (evaluation/golden dataset/rubric), 10 (pre-launch tests), 05 (resolution acceptance tests), 02 (acceptance criteria); master prompt golden-case list
**Related:** [REQUIREMENTS-TRACEABILITY.md](REQUIREMENTS-TRACEABILITY.md), [SECURITY-THREAT-MODEL.md](SECURITY-THREAT-MODEL.md)

## 1. Test identifier conventions

| Prefix | Meaning |
|---|---|
| `AT-<REQ-ID>` | Acceptance test verifying that requirement (e.g. `AT-PAY-05`); the traceability matrix references these 1:1 |
| `ER-01..11` | Entity-resolution acceptance set (doc 05) |
| `GC-01..15` | Golden research cases (doc 12 + master prompt) |
| `E2E-01..10` | End-to-end slices (doc 13) |
| `SEC-01..15` | Security gate (doc 10) |
| `QG-*` | Automated quality-gate checks (run per generation, and as tests against fixtures) |

Requirement IDs appear in test names/tags so CI can emit a traceability report (doc 02: IDs preserved in tickets, tests, PRs).

## 2. Layers and tooling

| Layer | Tooling | Scope |
|---|---|---|
| Unit (web) | Vitest | validation, state transitions, UI logic, zod schemas |
| Unit (worker) | pytest (+hypothesis for property tests) | URL safety, entity scoring, claim handling, length controller, ledger, freshness, routing (doc 13 unit list) |
| Integration | pytest + local Supabase; recorded provider cassettes | OAuth flows, search/fetch adapters, gateway, Razorpay test mode, queue/storage, PDF, email (doc 13 integration list) |
| E2E | Playwright Test against `DEMO_MODE=1` stack | the ten slices + journey variants |
| Security | dedicated suites + CI scanners | SEC-01..15 |
| Evaluation | golden-suite harness (fixtures; also runnable against live providers in staging) | GC cases, rubric scoring support |

## 3. Unit-test priorities (densest coverage mandated)

1. **SafeFetcher URL/IP policy** — table-driven: schemes, localhost, RFC1918/link-local/metadata, IPv6, redirects, rebinding (feeds SEC-03).
2. **Entity confidence scoring** — doc 05 weights/negative factors/label thresholds; property: score monotone in positive factors, bounded 0–100.
3. **Entitlement ledger** — property-based: any interleaving of grant/reserve/consume/release/restore/expiry preserves invariants ERD §5 (feeds SEC-07).
4. **Length controller** — class selection from complexity signals; trim protocol never removes protected blocks; ≤2 passes; annex excluded.
5. **Claim/evidence validation** — material claims require evidence ids; claim-type ↔ language-label mapping; freshness classification (REPORT-08/09 windows).
6. **ModelGateway** — payload allowlist rejects identity/billing/letterhead fields; ZDR params on every call; cost caps; schema-repair single retry; `NoApprovedCapacity` raise (feeds SEC-11).
7. **State machine** — illegal transition rejection for every (state, event) pair; side-effect table (QUEUE §5).
8. **Webhook processing** — signature, replay, out-of-order, idempotent grants.
9. **BriefDocument** — schema round-trip, system-draft immutability guard, origin-flag recomputation on edit, unsupported-user-text warning detection (EDIT-04).

## 4. Entity-resolution acceptance set (`ER-*`, doc 05 verbatim)

Fixture site + registry data per case; run in CI; Phase 1 gate additionally requires a 30-company varied live test.

| ID | Case | Must hold |
|---|---|---|
| ER-01 | Exact CIN in site footer | strong_match; CIN captured as identifier |
| ER-02 | Legal name only in privacy policy | candidate generated from legal page; company_controlled evidence |
| ER-03 | Brand site, different legal entity (subsidiary) | brand ≠ identity; "operates the brand" phrasing (ENTITY-06) |
| ER-04 | Listed parent / private operating subsidiary | mismatch detected; both surfaced; user chooses scope |
| ER-05 | Renamed company | former name linked; current legal name primary |
| ER-06 | Two similar-name companies | ambiguous label; evidence shown; never auto-guessed |
| ER-07 | Inactive company | warning + successor/former-name prompt |
| ER-08 | Foreign parent, Indian subsidiary | Indian entity primary |
| ER-09 | No legal disclosures on site | asks for legal name/CIN; failed_no_charge if abandoned |
| ER-10 | Malicious page instructions | instructions ignored; `prompt_injection_suspected` set; candidates unaffected |
| ER-11 | Private-IP redirect chain | fetch blocked; resolution continues on other sources; recorded limitation |

## 5. Golden cases (`GC-*`)

Each fixture records (doc 12): the correct confirmed entity, must-find facts, expected regulatory touchpoints, unacceptable claims, must-ask questions, source expectations. The suite runs in demo mode in CI (deterministic) and against live providers in staging (benchmark, B3/B4).

| ID | Case (doc 12 / master prompt) |
|---|---|
| GC-01 | Simple software startup |
| GC-02 | Manufacturer with factory footprint |
| GC-03 | Regulated fintech |
| GC-04 | Health/pharma company |
| GC-05 | Consumer/food company |
| GC-06 | SaaS/data company |
| GC-07 | Public unlisted group |
| GC-08 | Listed company |
| GC-09 | Brand/legal-entity mismatch (brand ≠ subsidiary) |
| GC-10 | Cross-border investor context |
| GC-11 | Sparse private company (1-page brief; no padding) |
| GC-12 | Common-name adverse-media false positive (must NOT attribute) |
| GC-13 | Renamed company |
| GC-14 | Multi-entity operation (primary + ≤2 related) |
| GC-15 | Listed parent / private subsidiary + malicious-instruction page (master prompt + ER-04/ER-10 full-pipeline variant) |

Pass condition per case: correct entity, zero unacceptable claims, all must-find facts present or converted to explicit gaps/questions, expected touchpoints raised, quality gates pass. **GC-12 failing blocks release** (wrong-entity/adverse false positive is an automatic failure, doc 12).

## 6. Security suite (`SEC-*`)

Defined in [SECURITY-THREAT-MODEL.md §7](SECURITY-THREAT-MODEL.md): SEC-01 RLS/IDOR matrix, SEC-02 signed-link expiry/reuse, SEC-03 SSRF, SEC-04 prompt injection, SEC-05 malicious files, SEC-06 webhook forgery/replay, SEC-07 entitlement races (property-based), SEC-08 trial abuse, SEC-09 log redaction, SEC-10 secret scan, SEC-11 ZDR/gateway, SEC-12 dependency+container scans, SEC-13 rate limits, SEC-14 deletion/retention verification, SEC-15 backup-restore rehearsal. All fifteen are a **paid-launch blocking gate**.

## 7. End-to-end slices (`E2E-*`, doc 13; all runnable in demo mode)

| ID | Slice | Key assertions |
|---|---|---|
| E2E-01 | website → entity candidates | INTAKE-01/02/03, ENTITY-01/02, no entitlement touched |
| E2E-02 | confirmed entity → evidence bundle | evidence reviewable without prose; metadata complete (Phase 2 gate) |
| E2E-03 | evidence → clarifications + questions | mandatory role; reasons shown; no confidential solicitation |
| E2E-04 | evidence + answers → BriefDocument | composer uses approved claims only; sections A–G; 8–20 questions |
| E2E-05 | BriefDocument → PDF | 1–4 pages; annex outside cap; deterministic re-render; **includes worker kill/resume mid-job** (checkpoint recovery, NFR-01) |
| E2E-06 | account → queued report | OAuth, dashboard statuses, truthful stages |
| E2E-07 | payment → entitlement → consume | webhook-authoritative grant; consume only post-gates |
| E2E-08 | failure → restore/refund | injected terminal failure → release/restore + email; single-purchase refund offer |
| E2E-09 | edit → version → letterhead PDF | immutable v0; version chain; warning on unsupported text; letterhead absent from all model-call recordings and logs |
| E2E-10 | issue → investigation → correction | version pinned; admin restore; correction = new version; original preserved |

## 8. Automated quality gates (`QG-*`, per generation; doc 12)

Entity consistency; 100% material-claim evidence linkage; zero unsupported numerical claims; zero unresolved high-severity conflicts; page count 1–4; question set present (8–20, role-tagged); source annex present; disclaimer verbatim; no prohibited data; PDF renders cleanly. Implemented in stage 11; also executed as fixture tests against known-bad BriefDocuments (each gate must individually catch its violation).

## 9. Lawyer-review rubric and release targets (doc 12)

Rubric (1–5): entity correctness, business understanding, corporate/governance usefulness, industry/competitor usefulness, regulatory spotting, matters for attention, kickoff questions, sources, concision, overall preparedness. **Release targets:** no critical category below 3; average ≥4; zero wrong-entity reports; zero known unsupported material claims; ≥30 lawyer-reviewed Mandate Briefs pass (charter launch gate). Review tooling: admin export of brief + provenance for reviewer scoring; scores stored for the learning loop.

## 10. MVP acceptance criteria mapping (doc 02)

The build is accepted only when these all pass end-to-end: entity confirmation (ER suite + E2E-01), durable queueing (E2E-05/06), claim provenance (QG + E2E-04), entitlement restoration (E2E-08), versioned editing (E2E-09), safe letterhead rendering (SEC-05 + E2E-09), reproducible PDF (E2E-05), tenant isolation (SEC-01), payment/provider cost reconciliation (E2E-07 + reconciliation job assertions).

## 11. CI pipeline stages

1. Lint + typecheck (ESLint/Prettier/tsc; Ruff/mypy).
2. Secret scan (gitleaks) + dependency audit (pnpm audit, pip-audit) + container scan (trivy) — SEC-10/12.
3. Shared-schema codegen check (generated artifacts in sync).
4. Unit suites (web, worker).
5. Integration (local Supabase service container, cassettes).
6. Demo-mode E2E (Playwright) + golden suite (fixtures).
7. Traceability report: fail if any `AT-*` tag references an unknown requirement ID or any requirement marked `Verified` lacks a passing tagged test.

Staging-only (manual/scheduled): live-provider golden benchmark, load smoke (2 concurrent jobs on KVM 2 sizing — R-03), SEC-15 restore rehearsal.
