# Demo fixtures

Offline, deterministic provider responses used when `DEMO_MODE=1`.

`manifest.json` is the catalog source of truth. Its nine entries cover the C8
adapter boundary: search, page fetching, company data, regulatory and litigation
sources, model routing, queue, storage and email. Every Phase 0 payload is synthetic
and intentionally minimal; feature-specific golden cases are added in the phase
that implements that behaviour.

Do not put credentials, personal data, user work product, letterhead, confidential
material, or unsupported MCA/legal-database claims in this directory. If a payload
changes, update its SHA-256 in the manifest in the same commit.
