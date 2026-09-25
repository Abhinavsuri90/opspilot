# ADR 002: Use S3Mock for local object-storage emulation

Status: accepted for Phase 0

## Context

The spec names MinIO for local S3-compatible storage. Its Docker Hub image no longer pulls, and the upstream Quay reference returned HTTP 401 during setup on 2026-09-26. Object storage is not used by Phase 0 code, but a clean `make up` should still start every declared service.

## Decision

Use Adobe S3Mock in local Compose. Keep storage integration behind an S3-compatible interface in Phase 1; use managed S3 or R2 for deployments as planned. The local mock has a persistent volume and a `documents` bucket.

## Consequences

S3Mock emulates a subset of S3 behavior. Phase 1 must test its required operations and include integration coverage against the actual staging object store before relying on presigned URLs or lifecycle policies. This differs from the named local product in `SPEC.md`, while preserving the S3-compatible architecture in `SYSTEM_DESIGN.md`.
