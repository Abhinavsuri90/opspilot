import { diffRows, type DiffResponse } from "@/lib/actions";

/**
 * Exactly what an action will change: a before/after table when the connector
 * knows the prior state, otherwise the values it will send, plus the connector's
 * own plain-text rendering (request line, signature note, columns).
 */
export function DiffPreview({ preview, compact = false }: { preview: DiffResponse; compact?: boolean }) {
  const rows = diffRows(preview);
  const hasBefore = preview.before !== null;
  return <div className="space-y-2" data-testid="diff-preview" data-kind={preview.kind}>
    {preview.title && <p className="break-all font-mono text-xs font-semibold text-slate-700">{preview.title}</p>}
    {rows.length > 0 && <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[280px] table-fixed border-collapse text-left text-xs">
        <caption className="sr-only">{hasBefore ? "Values before and after the action" : "Values the action sends"}</caption>
        <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="w-[32%] px-3 py-2 font-bold">Field</th>
            {hasBefore && <th scope="col" className="px-3 py-2 font-bold">Before</th>}
            <th scope="col" className="px-3 py-2 font-bold">{hasBefore ? "After" : "Value"}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map(row => <tr key={row.key} data-changed={row.changed || undefined} className={row.changed ? "bg-amber-50/60" : ""}>
            <th scope="row" className="break-words px-3 py-2 font-semibold text-slate-700">{row.key}</th>
            {hasBefore && <td className={`break-words px-3 py-2 ${row.changed ? "text-rose-800 line-through decoration-rose-300" : "text-slate-500"}`}><pre className="whitespace-pre-wrap break-words font-sans">{row.before}</pre></td>}
            <td className={`break-words px-3 py-2 ${row.changed ? "font-semibold text-emerald-900" : "text-slate-800"}`}><pre className="whitespace-pre-wrap break-words font-sans">{row.after}</pre></td>
          </tr>)}
        </tbody>
      </table>
    </div>}
    {rows.length === 0 && preview.lines.length === 0 && <p className="text-xs text-slate-500">This action sends no values.</p>}
    {preview.lines.length > 0 && (compact
      ? <details><summary className="cursor-pointer text-xs font-semibold text-slate-600">Request lines</summary><pre className="mt-2 overflow-x-auto rounded-xl bg-slate-900 p-3 font-mono text-[11px] leading-5 text-slate-100">{preview.lines.join("\n")}</pre></details>
      : <pre className="overflow-x-auto rounded-xl bg-slate-900 p-3 font-mono text-[11px] leading-5 text-slate-100">{preview.lines.join("\n")}</pre>)}
  </div>;
}
