import type { components } from "@/lib/schema";

type RuleResult = components["schemas"]["RuleResultResponse"];

const outcomes = {
  pass: { label: "Pass", glyph: "✓", className: "border-emerald-200 bg-emerald-50 text-emerald-800" },
  fail: { label: "Fail", glyph: "✕", className: "border-rose-200 bg-rose-50 text-rose-700" },
  skipped: { label: "Not evaluable", glyph: "–", className: "border-slate-200 bg-slate-50 text-slate-500" },
} as const;

function outcomeOf(rule: RuleResult) {
  return rule.passed === null ? outcomes.skipped : rule.passed ? outcomes.pass : outcomes.fail;
}

/** Cross-field rules from the workflow configuration, evaluated against the current values. */
export function RuleResults({ rules }: { rules: RuleResult[] }) {
  return <section aria-label="Rule results" className="rounded-2xl border border-slate-200 bg-white p-4">
    <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-bold text-slate-900">Rules</h3><span className="text-xs text-slate-500">{rules.filter(rule => rule.passed === false).length} failing</span></div>
    {rules.length === 0 && <p className="mt-2 text-xs text-slate-500">This workflow has no cross-field rules.</p>}
    <ul className="mt-3 space-y-2">
      {rules.map(rule => {
        const outcome = outcomeOf(rule);
        return <li key={rule.name} className="flex items-start gap-3 text-sm" data-outcome={outcome.label}>
          <span aria-hidden="true" className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border text-xs font-bold ${outcome.className}`}>{outcome.glyph}</span>
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-slate-900">{rule.name.replaceAll("_", " ")} <span className="sr-only">{outcome.label}</span><span aria-hidden="true" className={`ml-2 rounded-full border px-2 py-0.5 text-[11px] font-bold ${outcome.className}`}>{outcome.label}</span></p>
            <p className="mt-0.5 text-xs text-slate-600">{rule.message}</p>
            <code className="mt-1 block break-words text-[11px] text-slate-400">{rule.expression}</code>
          </div>
        </li>;
      })}
    </ul>
  </section>;
}
