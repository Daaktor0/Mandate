# Phase 2 security review — golden fixtures

**Scope:** GC-01..15 synthetic research inputs and machine-checkable expectations.

The corpus is an evaluation boundary, not a provider input bypass. The worker
loader requires exactly the 15 IDs listed in the test plan and validates the
filename/ID relationship, typed expectation shape and bounded file size before
returning cases to a test harness.

| Threat | Control | Evidence |
|---|---|---|
| A fixture silently becomes a live research source | Every URL is restricted to reserved example/.example hosts; the corpus carries metadata only and makes no network or model call | test_REPORT_06_golden_loader_rejects_non_reserved_url; loader URL policy |
| Raw fetched material or prompt text reaches tests or persistence | Inputs contain identifiers, topics and source flags only; recursive validation rejects raw body/text/HTML and sensitive fields | test_REPORT_06_golden_loader_rejects_sensitive_or_raw_fields; all 15 JSON cases |
| Credentials, account, firm or confidential matter data are embedded | Recursive key denylist rejects credentials, billing, identity, firm, letterhead and confidential fields | golden.py safe-value validator |
| A missing case weakens the release gate | The loader rejects anything other than exactly GC-01 through GC-15; case IDs must match filenames | test_REPORT_06_golden_loader_rejects_missing_case |
| Brand, parent or adverse-media identity is conflated | Expectations preserve the correct entity and explicit negative quality gates for GC-09, GC-12 and GC-15; GC-12 is marked release-blocking | test_REPORT_06_GC_12_wrong_entity_is_release_blocking_expectation |
| Untrusted page instructions are followed | GC-15 records promptInjectionSuspected as a source signal and requires ignore_untrusted_page_instructions and prompt_suspect_support_excluded | test_REPORT_06_GC_15_injection_page_is_data_not_instruction |

The corpus is synthetic and zero-spend. It does not claim the live B3/B4
provider benchmark, the Phase 1 B5 master-data benchmark, or lawyer review.
Those remain explicit human/vendor gates.
