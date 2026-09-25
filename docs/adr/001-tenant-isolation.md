# ADR 001: Tenant isolation with scoped repositories and Postgres RLS

Status: accepted for Phase 0

## Context

Shared tables keep early deployments simple, but an application query missing an organization filter could expose another customer's data. Authentication also needs to find a user and organization before a tenant context exists.

## Decision

`organizations` and `users` are global identity tables. Every tenant-owned table has `org_id` and a forced row-level-security policy. A request sets `app.current_org` with `set_config(..., true)` in its transaction, and repository methods require an `org_id` in their tenant queries. The API uses a dedicated non-owner database role. Its audit grants allow reads and inserts, but no updates or deletes.

## Consequences

Tests need a real Postgres instance and must connect as the application role to prove policies work. Seed and migrations connect as the owner role; the owner credentials must never be used by the API. Future tenant tables must get RLS and grants in their own migration before a feature ships.
