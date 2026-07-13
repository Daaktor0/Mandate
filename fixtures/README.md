# Fixtures

`demo/` contains zero-spend adapter fixtures. `golden/` contains evaluation cases.
Fixtures must contain public or synthetic data only; account, billing, user-work-product,
branding and confidential inputs are prohibited.

The demo catalog is versioned by `demo/manifest.json`. Every capability has one
Phase 0 smoke recording with a SHA-256 digest. The worker validates completeness,
paths and digests before enabling `DEMO_MODE=1`.
