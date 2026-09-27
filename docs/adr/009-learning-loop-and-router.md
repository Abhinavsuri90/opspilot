# ADR 009: Learning loop, model router, cost ledger and daily budget

Status: accepted for Phase 5

## Context

After Phase 4 every extraction ran one model once, nothing was learned from reviewer
corrections, and the cost of a document was unknown. Phase 5 has to make the system
visibly improve from its own corrections, spend money only where the cheap model is unsure,
account for every model call, and stop a tenant from running up the bill. The rules were the
same as before: every tenant table behind row-level security, no external call without a
recorded outcome, deterministic behaviour under test, and nothing that changes a value
without evidence a reviewer can see.

## Decision

### One call path and one ledger (`app/llm/client.py`, `app/llm/pricing.py`)

Every model call goes through `call_chat` (chat completions) or `record_local_call`
(deterministic providers). Both write an `llm_calls` row for success **and** failure with
purpose (`extraction`, `escalation`, `embedding`, `agent`), provider, model, prompt version,
tokens, cost, latency, `ok`, a document-free error string and the document's trace id. The
rules and mock providers record rows too, at zero cost, so per-document cost is always
defined. Cost comes from a price table (cents per one million tokens, input and output) keyed
by OpenRouter model id: a small built-in table merged with `LLM_PRICE_TABLE_JSON`. A model in
neither place records a null cost and one warning per process; the KPIs count those calls
separately (`cost_unpriced_calls`) instead of pretending they were free. The ledger is
`SELECT, INSERT` only for the application role and is scoped by `org_id` under RLS. Recording
is best effort: a ledger write failure is logged and never fails an extraction.

### Prompts as reviewed files (`app/prompts/`)

Each prompt is a Markdown file with YAML front-matter (`version`, `purpose`). The loader
validates the version format and purpose, rejects empty bodies and duplicate versions, and the
test suite runs it over the directory. `extraction-v3` is `extraction-v2` plus a delimited
block of retrieved examples, rendered as data ("earlier extraction" / "reviewer-confirmed
value" next to the document line), never as instructions.

### Two-tier router (`app/llm/router.py`)

Tier 1 (`LLM_TIER1_MODEL`, default `OPENROUTER_MODEL`) extracts every field. A field is
*failing* when it scores below its threshold, when a required field is missing, or when a
cross-field rule that references it fails. If any field fails and tier 2
(`LLM_TIER2_MODEL`) is configured, tier 2 is asked for exactly those fields: the JSON schema's
name enum is restricted, the prompt lists only those fields, and the ledger row's purpose is
`escalation`. The `model_agreement` signal (weight 0.10, reserved since ADR 006) is 1.0 when the
two values match after whitespace collapse and case folding, 0.0 when they differ, and `None`
for fields that were never escalated. On disagreement the tier-2 value is kept and the field
carries the reason "Models disagreed"; when tier 2 finds nothing it can ground, the tier-1
row stays with agreement 0.0 so the reviewer still sees evidence. A tier-2 outage keeps the
tier-1 result (it was already reviewable). `extraction_runs` records `tier1_model`,
`tier2_model`, `escalated`, `cost_cents` and the per-field agreement in `raw_json`. With the
rules provider a tier 2 exists only as a test double.

### Memory (`app/memory.py`, `memory_items`)

Memory is per organization, behind RLS, and every query is scoped by `org_id`; a test proves
that one tenant's examples are never retrieved for another and that a write under the wrong
tenant context is rejected by the database. Two kinds of item share one table:

- **Vendor profile** (unique per `org_id` and normalized vendor key): typical currency (most
  common code seen), per-field format patterns (digits become `9`, letters `A`, punctuation
  and spacing kept; at most eight patterns per field), last values, document count.
- **Few-shot example**: field, the value the extractor produced, the value the reviewer
  confirmed, the document line the value came from, and a 256-dimension embedding.

The loop writes on every field **edit** (that correction becomes an example) and on
**approval** (the effective values feed the profile and every edit of the review is
re-confirmed). Examples are deduplicated on (field, wrong value, correct value) and bounded at
20 per vendor; when the bound is reached the oldest example is overwritten, so the application
role needs `UPDATE` but never `DELETE`. Only the party field (`vendor` or `supplier`) keys the
memory; a document without one teaches nothing.

At extraction time the worker loads, before calling the model, the profiles whose vendor name
appears in the page text and the three most relevant examples: same vendor first, then cosine
distance between the example's embedding and the page-text embedding (pgvector `<=>` on
Postgres, the same ordering in Python under SQLite), then recency. The examples go into the
`extraction-v3` prompt; the profile feeds the `memory_prior` signal (weight 0.05): for a
currency field 1.0 when it equals the typical currency else 0.3, for other fields 1.0 when the
value's format pattern was seen before else 0.5, `None` when the profile has nothing to say.

**Embeddings.** The default embedder needs no external model: unigrams and bigrams are
feature-hashed (BLAKE2, signed) into 256 dimensions and L2-normalized, so retrieval works
offline, deterministically and for free. An OpenAI-compatible endpoint (`EMBEDDINGS_BASE_URL`,
`EMBEDDINGS_MODEL`, `EMBEDDINGS_API_KEY`, `dimensions=256`) can replace it behind the same
interface; those calls are metered as purpose `embedding` and respect the daily budget. When it
fails the example is stored without a vector and is still found by vendor match. Switching
embedders invalidates existing vectors (different spaces); that is a documented operational
step, not something the code guards.

### Daily budget (`app/llm/budget.py`)

`org_settings.daily_llm_spend_cap_cents` (null = unlimited; the demo organizations are seeded
with 100) is compared with the sum of `llm_calls.cost_cents` for the current UTC day
immediately before a paid tier-1 call, again before a paid tier-2 call, and before a remote
embedding. When the cap is reached the worker either extracts with the rules provider
(`LLM_BUDGET_FALLBACK=rules`) or hands the document back to the queue until 00:05 UTC the next
day without spending an attempt (`defer`, the default), with `failure_reason` "Daily model
budget reached" visible on the document. The organization gets one `llm.budget_reached` audit
event per day, whichever outcome applies. Free providers are never gated.

### KPIs and evals

`/v1/metrics/overview` gains cost per processed document (cents; null until the range has a
recorded call), total cost, unpriced calls, token totals, and the escalation rate over the
latest runs. `/v1/metrics/accuracy?weeks=12` returns one point per ISO week (Monday, UTC) with
fields assessed, fields edited and accuracy, over the documents the caller may see.

`evals/run.py` now scores every document through the router with an in-memory ledger, so the
report states calls, tokens, cost and latency percentiles exactly as the worker would have
logged them. The learning scenario holds out half of each vendor's documents, scores them cold,
ingests the other half's ground truth as reviewer corrections into an isolated in-memory copy of
`memory_items`, scores the held-out half again with that memory, and fails the run if exact
match or flag recall regressed (strictly for the mock, within 0.02 for a live model). The
baseline comparison keeps its 0.02 tolerance. CI runs the deterministic evaluation on every
push. A 20-document live tier-1 evaluation can be requested manually with the workflow's
`live_eval` input and requires an `OPENROUTER_API_KEY` secret; normal pushes never spend credits.

## Consequences

- Model-call outcomes are written to one table used by the budget, KPIs and timeline. Writes
  are best effort and costs come from a local price table, so these are estimates rather than
  complete provider billing records.
- Escalation is bounded to the fields that need it, which keeps tier-2 spend proportional to
  uncertainty; the agreement signal makes a disagreement visible to the reviewer.
- With the deterministic providers memory only changes confidence (the prior), not values, so
  the mock learning scenario proves plumbing and no-regression; the accuracy gain from
  examples is only measurable with a live model.
- `CREATE EXTENSION vector` needs a superuser or a pre-installed extension; every compose file
  runs migrations as the bootstrap role of the `pgvector/pgvector:pg16` image.
- The built-in price table is a convenience; operators must verify catalogue prices and set
  `LLM_PRICE_TABLE_JSON` for the models they deploy, including the default tier-1 model.
- Memory rows contain document values (vendor names, corrected values, one document line each);
  they stay under RLS, are never logged, and a future retention setting must purge them with the
  documents.
