# Phase 2 security review — File-safety boundary

**Review date:** 2026-07-17  
**Scope:** reusable malware-scan, archive-limit and sandbox-parser gate for quarantined filing binaries  
**Requirements/tests:** RUN-06, NFR-03/05, SEC-05/09

## Security conclusion

Quarantined PDF/ZIP filing binaries can now be turned into bounded text through one
mandatory sequence — quarantine-integrity verification, malware scanning, archive-limit
enforcement and attested sandbox parsing — and through nothing else. The boundary is
fail-closed at every step: any digest, size, verdict, archive or attestation problem
raises a stable `FileSafetyError` code and no text is produced. Parsed text is returned
as `untrusted=true`, `evidence_admitted=false` output; this slice admits nothing as
Evidence and has no route to a model, the composer or the `evidence`/`claims` tables.

## Quarantine integrity

`QuarantinedBinary` pairs a `CorporateFilingReference` with its bytes and refuses to
exist unless the bytes are non-empty, at most 25 MiB, exactly the recorded size and a
constant-time SHA-256 match for the recorded digest. The reference must still be
`pending_malware_scan` with `parse_allowed=false`. Error codes never include document
bytes or source paths.

## Malware scanning

- The scanner contract returns only an audit-safe verdict model; raw scanner output is
  structurally excluded, and clean verdicts cannot carry threat names (nor infected
  verdicts omit them).
- `DEMO_MODE=1` selects the SHA-256-allowlisted deterministic fixture scanner. A binary
  absent from the allowlist fails closed as `malware_fixture_missing` — demo mode has no
  clean-by-default path.
- Live mode may explicitly select `clamd_unix`: a local ClamAV `clamd` Unix-socket
  INSTREAM transport with bounded timeout, chunk size and reply length, no shell
  invocation and no file-path exposure. A missing socket path, connection failure,
  oversized reply, `ERROR` reply or unparseable reply fails closed; unavailability is
  marked retryable but never treated as clean.
- Unconfigured or unknown scanner bindings stop pipeline construction.
- Every ZIP member is scanned individually in addition to the outer archive scan, and
  each scan's reported digest must match the bytes the pipeline submitted.

## Archive limits

ZIP expansion is bounded before any member is read: at most 50 members, 25 MiB per
member, 100 MiB total uncompressed, compression ratio at most 100, stored/deflated
compression only. Member reads are chunked and stop at the declared size; a size
mismatch is rejected. Member names are rejected for traversal (`..`, `.`), absolute
paths, Windows separators/drive prefixes, NUL bytes, over-length names and case-folded
duplicates. Symlinked, encrypted and nested-archive members are rejected, as is any
non-PDF member. PDFs (standalone or members) must carry the PDF magic and are rejected
when ZIP signatures appear later in the body (polyglot suspicion).

## Sandbox-parser attestation

`SandboxParseResult` structurally requires `sandbox_profile="networkless_readonly_v1"`,
`network_disabled=true`, `read_only_filesystem=true` and `active_content_removed=true`,
plus a source digest that must match the submitted bytes and a self-consistent parsed-text
digest. The pipeline re-verifies the attestation and source digest on every result.

`DEMO_MODE=1` replays the pinned deterministic parser fixture and performs no real PDF
parsing. **No live parser binding is allowlisted.** Live PDF parsing stays fail-closed —
including when ClamAV is configured and healthy — until the parser genuinely runs in an
isolated networkless, read-only, resource-limited service/container and returns the
required attestation. Selecting any live parser name today stops pipeline construction.

## Verification coverage

`services/worker/tests/test_file_safety.py` exercises the hostile-file corpus
foundations: digest/size mismatches; infected, unknown and unavailable scanner
outcomes; clamd INSTREAM framing against a real Unix-socket fake and reply parsing;
media-type mismatches, unrecognised bytes and PDF/ZIP polyglots; traversal, absolute,
Windows-style, drive-prefixed and case-folded-duplicate member names; symlinks,
encrypted members, nested archives and corrupt archives; decompression-bomb ratios and
member-count/member-size/total-uncompressed limits; parser source-digest mismatches,
non-weakenable attestations and missing parser fixtures; fail-closed provider selection
for both capabilities; and successful demo PDF/ZIP parsing whose output remains
untrusted and unadmitted.

Full linting, formatting, typechecking, secret/dependency/container scans, unit suites,
database/container integration and requirements traceability must pass on the final PR
head before merge.
