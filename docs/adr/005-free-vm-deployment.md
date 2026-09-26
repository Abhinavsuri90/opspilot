# ADR 005: One free VM for the first hosted deployment

Status: deployment configuration implemented; Oracle account capacity and hosted acceptance pending.

## Context

The owner requires a $0 hosting plan and permits identity verification with a card. The existing Render Blueprint uses paid private API and worker services. Its free database alternative expires, and a combined free web service would pause the extraction worker while asleep.

## Decision

Provide an additive Oracle Always Free A1 deployment using Docker Compose. Caddy terminates HTTPS and forwards to Next.js. The API, worker and PostgreSQL have no host ports. PostgreSQL and Caddy state persist in named volumes; PDFs live in a private OCI bucket. A separate migration container receives owner credentials; serving processes retain the restricted application role. All eight pages keep the same origin and authentication flow.

Use the rules provider for a deployment without model API spending. Initial startup creates no accounts or fictional organizations. Optional OpenRouter credentials belong only to the worker.

## Consequences

- One VM and one PostgreSQL instance are single points of failure. The operator owns patching, backups, restore drills and capacity monitoring.
- Oracle free capacity may be unavailable and idle instances can be reclaimed. This configuration does not establish an uptime SLA or measured production performance.
- API/web health checks and durable job leases remain separate from worker progress; hosted acceptance must include actual extraction.
- The paid Render configuration remains a supported alternative if the budget changes. The local Compose file remains a development environment.
- Images are built from the checked-out source on the VM. Updates are explicit and migrations precede reopening traffic.

See [the deployment runbook](../deployment.md) for current provider limits, setup commands and verification gates.
