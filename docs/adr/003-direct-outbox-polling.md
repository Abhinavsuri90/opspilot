# ADR 003: Poll the transactional outbox directly for the first extraction slice

Status: accepted for the local Phase 1 prototype

## Context

The target design uses a Postgres outbox dispatcher to publish committed jobs to separate Redis queues. Document intake needs a durable worker now, while review, actions, browser automation, and independent queue scaling are still unimplemented.

## Decision

Write the document and outbox event in the same database transaction. A dedicated worker polls unpublished extraction events using the restricted app database role. It rotates its starting organization after each claim so one tenant's continuous backlog does not always precede another's. It sets the tenant context for each organization, claims an event with row locking, and writes the extraction result and audit event before marking the outbox event complete. Failed storage or provider calls retry with a short delay; claims older than five minutes can be reclaimed.

## Consequences

- A worker restart or transient error does not discard the intake event. The UI can display queued, extracting, failed, or needs-review state.
- A slow provider occupies the single worker process; throughput and latency are not yet measured at scale. Long calls may exceed the five-minute claim lease. Production use needs a dispatcher, separate queues, concurrency limits, monitoring, and more robust lease management.
- Redis remains in local Compose for the planned queue architecture but is not part of the current extraction path. This is a deliberate deviation from the full design in `SYSTEM_DESIGN.md` and `SPEC.md`.
