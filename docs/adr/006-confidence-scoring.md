# ADR 006: Multi-signal field confidence with per-field thresholds

Status: accepted for Phase 2

## Context

A model's own confidence is a weak predictor of whether an extracted value is right. Reviewers need to know *why* a field is doubtful, and the routing decision (auto-approve or send to a human) must be explainable and tunable per customer without code changes. The score therefore combines independent checks, each of which can be shown to a reviewer as a reason.

## Decision

`app/confidence.py` scores every extracted field from six signals, each in `[0, 1]` or `None` when it does not apply:

| Signal | Weight | What it measures |
|---|---|---|
| grounding | 0.35 | The evidence string is found verbatim on the cited page (1.0), only after whitespace normalization (0.7), or not at all (0.0). The value must also appear inside its evidence. |
| format | 0.25 | The value parses as its configured type (date, money, integer, currency code) and passes the field's regex and enum, if any. |
| cross_field | 0.20 | Every configured rule that references the field passes (1.0) or at least one fails (0.0). `None` when no rule referencing the field could be evaluated. |
| model_agreement | 0.10 | Reserved for the tier-2 router: do the cheap and strong models agree? `None` until Phase 5. |
| memory_prior | 0.05 | Reserved for vendor memory: is the value consistent with the known vendor profile? `None` until Phase 5. |
| self_report | 0.05 | The provider's own confidence, when it reports one. |

The score is the weighted mean over the signals that are not `None`; weights are renormalized so that a field assessed by grounding and format alone still spans the full `0..1` range. A field whose score is below its configured threshold, or a required field that is missing, is flagged `needs_review` with human-readable reasons. Thresholds live per field in the organization's `WorkflowConfig` (`FieldSpec.threshold`, default 0.8, 0.9 for invoice totals), so a customer can tighten or relax review pressure per field and per document type. Rules use the safe expression grammar in `app/rules.py`; a rule that cannot be evaluated because an operand is missing is reported as `None`, never as a failure.

Why these weights:

- **Grounding dominates** because a value that cannot be found in the document is the single strongest sign of hallucination, and it is the check least likely to be fooled by a plausible looking answer. It is also fully deterministic.
- **Format** is the second largest weight because a malformed date or amount will break downstream actions regardless of how the model felt about it.
- **Cross-field rules** are cheap arithmetic that catches transposed digits and wrong totals; they carry less weight than format because a single unparseable sibling makes them unevaluable.
- **Self-report is deliberately weak** (0.05). Model self-assessments are poorly calibrated and easily saturated near 1.0; the signal is kept so that a low self-report can still nudge a borderline field into review, but it can never rescue a field that failed grounding or format.
- The two reserved signals are recorded now so the stored `signals_json` shape is stable when the router and memory arrive.

Document routing: with `review_policy: "always"` (the default, which preserves the Phase 1 behavior) every document goes to review; with `"threshold"` a document is `auto_approved` only when no field is flagged and no rule failed.

## Consequences

- Reviewers see the signal breakdown and reasons for every flagged field, and the review queue's `flagged_count` comes from the same assessment.
- Weights are constants in code; changing them is a code change reviewed alongside the eval (`evals/run.py` reports flagging precision and recall against a stored baseline).
- A rule failure flags every field the rule references, including the correct ones, because the engine cannot tell which operand is wrong. The eval baseline records this as reduced flagging precision on rule-mismatch cases.
- Corrections are append-only rows; the assessment of the original extraction is never rewritten, which keeps the training signal for the learning loop intact.
