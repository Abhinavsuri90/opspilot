# ADR 002: Use S3Mock for local object-storage emulation

Status: accepted for local development

## Context

The spec names MinIO for local S3-compatible storage. Its Docker Hub image no longer pulls, and the upstream Quay reference returned HTTP 401 during setup on 2026-09-26. A clean `make up` should start every declared service, including the storage used by the invoice intake workflow.

## Decision

Use Adobe S3Mock in local Compose. Keep storage integration behind an S3-compatible interface; use managed S3 or R2 for deployments as planned. The local mock has a persistent volume and a `documents` bucket. It runs as root in Compose because the Docker named volume starts root-owned and otherwise upload returns HTTP 500.

## Consequences

S3Mock emulates a subset of S3 behavior. Local upload and worker download passed a browser smoke test. Staging still needs an integration check against the real object store before relying on presigned URLs or lifecycle policies. This differs from the named local product in `SPEC.md`, while preserving the S3-compatible architecture in `SYSTEM_DESIGN.md`.
