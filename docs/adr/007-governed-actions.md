# ADR 007: Governed actions, checked immediately before every external call

Status: accepted for Phase 3

## Context

After a document is approved, OpsPilot pushes its values into customer systems (a webhook, a
Postgres table, a Google Sheet, a CSV export). Those are the only moments the agent changes the
world outside its own database, so they need the strongest controls: a human decision where
the customer wants one, an emergency stop that works instantly, a rehearsal mode for the first
days at a customer, and safety against duplicates, hostile destinations and credential leaks.

## Decision

**Every side effect is an `actions` row.** The worker turns an approved document into one action
per enabled destination of the workflow configuration the document was processed with (its pinned
version). Each row carries the resolved payload, a human-readable preview (`Diff`), the policy that
applied, an idempotency key and a version for optimistic concurrency. Documents move
`approved | auto_approved -> actions_pending -> completed`; a document stays `actions_pending`
while any action is `proposed`, `approved`, `executing`, `retrying` or `dead_lettered`.

**Policy is resolved twice, and the second time wins.** At proposal time the effective policy
(`action_policies` row for the organization, else the config default, else `needs_approval`)
decides whether the action starts `approved` (auto), `proposed` (waits for a reviewer or
administrator) or `forbidden` (audited, never executed). At execution time the worker re-reads the
organization's `org_settings` row `FOR SHARE` and the policy row again, in the same transaction that
marks the action `executing`, immediately before the connector call:

- kill switch on: nothing runs; the action keeps its status, is re-checked after 60 seconds and
  the block is audited at most once per hour per action (or when its attempt count changes);
- policy now `forbidden`: the action becomes `forbidden`;
- shadow mode on: the action becomes `shadowed`, its preview is stored as the result, and the
  connector is never called;
- otherwise the action becomes `executing` and the connector runs outside the transaction under a
  hard wall-clock limit (`ACTION_EXECUTE_TIMEOUT_SECONDS`, default 30 s).

`FOR SHARE` on the settings row means an administrator's kill-switch commit either lands before
this read (and stops the run) or waits for the gate transaction to finish; there is no window in
which a switch flipped after approval is ignored for an execution that starts after the commit.

**Idempotency.** The key is `sha256(org, document, destination, action type, canonical payload)`,
unique per organization. Proposing the same document twice creates nothing new; a changed value
after a reopen creates a new action. Connectors receive the key: the webhook sends it in
`X-OpsPilot-Idempotency-Key`, the CSV export and Google Sheets connectors keep it in the first
column and skip a key they already find, and the Postgres connector inserts
`ON CONFLICT (opspilot_action_id) DO NOTHING`. A worker that dies after the external call can
therefore replay the attempt safely.

**Retries and the dead-letter queue.** A retryable failure (network errors, timeouts, HTTP 408,
429 and 5xx, Postgres connection errors) reschedules the action with exponential backoff of
`2^attempt` minutes with plus or minus 20 percent jitter. After five attempts the action is
`dead_lettered`; a terminal failure (4xx, data errors, blocked destination) is `failed` after one.
Both keep the attempt log and can be retried by a reviewer or administrator, which resets the
attempt budget. Dead-lettered actions keep their document in `actions_pending` so they stay
visible; failed, rejected, forbidden, shadowed and succeeded actions settle.

**Credentials at rest.** Connector credentials are validated per connector type with Pydantic,
encrypted with Fernet under `CONNECTOR_ENCRYPTION_KEY`, stored in `credentials_encrypted`, and
never returned by the API (`has_credentials` only). The key is mandatory outside development;
development derives a local-only key from `JWT_SECRET` so the compose stack needs no extra
secret. Rotating the key without re-encrypting makes affected actions fail with a clear,
non-retryable error.

**Outbound destination guard.** Webhook URLs are tenant supplied, so the worker would otherwise be
an open proxy into the deployment's network. Outside development a webhook URL must be HTTPS,
must not embed credentials, and every address its host resolves to must be publicly routable
(no RFC 1918, loopback, link-local, metadata, CGNAT, IPv4-mapped or reserved ranges). The check
runs when the connector is saved and again immediately before each send; redirects are not
followed. Static headers may not override the `X-OpsPilot-*` signature headers.

**Webhook signature.** `X-OpsPilot-Signature: sha256=HMAC_SHA256(secret, "{timestamp}.{body}")`
over the canonical JSON body, with `X-OpsPilot-Timestamp` for replay windows on the receiver.

## Consequences

- The kill switch is a database row, not a process flag, so it applies to every worker replica
  and survives restarts. Engaging it does not cancel work already inside a connector call; that
  call finishes or times out, and nothing new starts.
- Shadow mode still requires human approval for `needs_approval` actions; what changes is that
  approval records the preview instead of executing. Reports comparing shadowed proposals with
  human decisions are Phase 4 work.
- Proposals use the pinned configuration version, so destinations added later apply to documents
  approved after that change. The append-only `workflow_configs` table and the
  `GET/POST /v1/settings/workflow` API make each version auditable.
- Google Sheets and the Postgres connector are verified against mocked or scratch destinations in
  CI; a live Google Sheets check needs a real service account shared on the target spreadsheet.
- Connector executions share the worker's bounded-thread pool with PDF parsing
  (`MAX_CONCURRENT_PARSES`), which caps concurrent external calls per process.
