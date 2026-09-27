# ADR 004: Share login attempt limits through Postgres

Status: accepted for the public demo path

## Context

Password verification uses Argon2 and is intentionally expensive. A public login endpoint needs a limit on repeated guesses. A process-local counter would reset on restart and would not be shared by multiple API replicas. The current deployment already depends on Postgres and has no edge rate-limiting service.

## Decision

Migration `0003` adds a `login_attempts` table keyed by a SHA-256 hash of normalized organization slug and email. Before password verification, the API atomically reserves an attempt in a 15-minute window. It permits 10 attempts and returns HTTP 429 for further attempts in that window. A successful login clears its counter. The restricted application role receives only the table permissions needed for this operation; old counters are pruned.

The counter is deliberately separate from tenant-owned invoice data: login occurs before the caller has an authenticated tenant context. The public error for incorrect credentials remains the same whether the account exists or not.

## Consequences

- Multiple API instances share the same limit, and restarts do not reset it.
- Each login now needs a short database write before Argon2 verification; database unavailability prevents sign-in.
- Someone who knows a login identity can temporarily exhaust its attempts. An edge per-IP limit or WAF is still advisable before publishing a widely shared demo account.
- The migration must run before deploying the updated API. Both deployment paths run `alembic upgrade head` as a separate owner-credential step before the API is restarted (see `docs/deployment.md`).
