# Golden fixtures

This directory contains the deterministic GC-01..15 evaluation corpus from
`docs/implementation/TEST-PLAN.md`. Each case is a separate JSON file and is
loaded by `mandate_worker.golden.load_golden_cases`.

Each file has four top-level fields:

- `caseId`: exactly the filename ID, `GC-01` through `GC-15`.
- `title` and `category`: the doc-12 scenario label.
- `inputs`: bounded synthetic identifiers, a reserved `.example` URL, an
  as-of date, an entity hint, focus topics and source metadata. It contains no
  fetched body, prompt, credential, account, firm, billing, letterhead or
  confidential matter narrative.
- `expectations`: the correct entity plus must-find facts, regulatory
  touchpoints, unacceptable claims, must-ask questions, source expectations and
  quality-gate codes.

The loader requires all 15 files, rejects unknown or mismatched IDs, limits
each file to 64 KiB, validates the typed shape, rejects sensitive/raw fields,
and permits only reserved `example`/`.example` URLs. The corpus is synthetic
and zero-spend. It is an evaluation input and expectation set; live-provider
quality and the B3/B4 benchmark remain separate launch evidence.
