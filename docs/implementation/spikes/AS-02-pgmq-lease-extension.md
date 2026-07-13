# AS-02 spike — pgmq visibility and lease extension

**Status:** Verified conditionally  
**Date:** 2026-07-13  
**Requirement:** NFR-01  
**Decision affected:** ADR-002 / AS-02

## Question

Are Supabase Queues (pgmq 1.x) visibility-timeout and lease-extension semantics sufficient for a Mandate job that may need a lease window of up to 30 minutes?

## Experiment

The Docker-backed Supabase workflow applied the repository migrations to Postgres 15 and ran `supabase/tests/database/queue_visibility.test.sql`. The isolated test queue exercised the real extension rather than the memory adapter.

The test proves:

1. `send` returns a durable message identifier.
2. `read` leases one message, increments `read_ct`, and hides it from another reader.
3. `set_vt(..., 1800)` accepts a 30-minute visibility extension.
4. A later committed `set_vt` call moves visibility further forward.
5. The message remains exclusive before expiry and is redelivered after expiry with an incremented `read_ct`.
6. `archive` removes the live message and retains one replayable archive record.

Clean-runner evidence: GitHub Actions run `29270126550`; all 16 initial behavioral assertions and database lint passed. The final test also pins the observed extension to the specified pgmq 1.x version line.

## Finding

pgmq `set_vt` calculates its new timestamp from PostgreSQL's transaction timestamp. The first version of the experiment called two extensions inside one long transaction; both produced the same `vt`, correctly falsifying the assumption that a heartbeat can share a long-running job transaction.

Repeating the experiment with each queue operation committed independently moved `vt` forward and passed the exclusivity and redelivery checks. This matches the worker architecture: queue heartbeats are control-plane operations and must not share pipeline-stage transactions.

## Decision and implementation constraint

AS-02 is verified with one binding constraint:

> Every pgmq `read`, `set_vt`, `archive` and dead-letter operation must complete in a short transaction, normally autocommit. A job or stage transaction must never remain open across lease heartbeats.

The constraint is documented on `AsyncQueueDatabase` and in the worker README. The native Postgres lease-table fallback in ADR-002 is not required. The next Phase 0 container/Compose slice must preserve autocommit behavior when it wires the concrete database pool.
