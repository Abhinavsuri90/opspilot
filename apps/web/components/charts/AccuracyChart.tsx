"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { components } from "@/lib/schema";

type AccuracyPoint = components["schemas"]["AccuracyPoint"];

/** Weekly reviewer correction signal. The table keeps exact values available to keyboard users. */
export function AccuracyChart({ points, loading }: { points: AccuracyPoint[]; loading: boolean }) {
  const rows = points.map(point => ({ ...point, percent: point.accuracy === null ? null : Math.round(point.accuracy * 1000) / 10 }));
  const measured = rows.some(row => row.percent !== null);
  return <section aria-labelledby="accuracy-heading" className="card mt-6 p-5 sm:p-6">
    <h2 id="accuracy-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Weekly field accuracy</h2>
    <p className="mt-1 text-xs leading-5 text-slate-500">Fields that reviewers did not edit, grouped by the week the document arrived. This reflects reviewer corrections, not an independent ground-truth check.</p>
    <div role="figure" aria-label="Weekly field accuracy, percent" aria-busy={loading || undefined} className="relative mt-4 h-56 w-full">
      {rows.length > 0 && <ResponsiveContainer width="100%" height="100%"><LineChart data={rows} margin={{ top: 12, right: 14, bottom: 4, left: 0 }}>
        <CartesianGrid vertical={false} stroke="#e2e8f0" />
        <XAxis dataKey="week_start" tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} minTickGap={20} interval="preserveStartEnd" />
        <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(value: number) => `${value}%`} width={40} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
        <Tooltip formatter={(value) => [typeof value === "number" ? `${value}%` : "—", "Accuracy"]} />
        <Line dataKey="percent" type="monotone" stroke="#0891b2" strokeWidth={2.5} connectNulls={false} dot={{ r: 3, fill: "#0891b2" }} isAnimationActive={false} />
      </LineChart></ResponsiveContainer>}
      {!measured && <p role="status" className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-sm text-slate-500">{loading ? "Loading accuracy…" : "No reviewed fields in this period yet."}</p>}
    </div>
    <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2 text-xs">
      <summary className="cursor-pointer font-semibold text-slate-700">Show weekly data</summary>
      <div className="mt-2 max-h-64 overflow-auto"><table className="w-full text-left"><caption className="sr-only">Weekly field accuracy and sample sizes</caption><thead><tr className="text-[10px] uppercase tracking-wide text-slate-400"><th scope="col" className="py-1 pr-3">Week starting</th><th scope="col" className="py-1 pr-3 text-right">Fields assessed</th><th scope="col" className="py-1 pr-3 text-right">Fields edited</th><th scope="col" className="py-1 text-right">Accuracy</th></tr></thead><tbody>{rows.map(row => <tr key={row.week_start} className="border-t border-slate-200"><th scope="row" className="py-1 pr-3 font-medium">{row.week_start}</th><td className="py-1 pr-3 text-right tabular-nums">{row.fields_assessed}</td><td className="py-1 pr-3 text-right tabular-nums">{row.fields_corrected}</td><td className="py-1 text-right tabular-nums">{row.percent === null ? "—" : `${row.percent}%`}</td></tr>)}</tbody></table></div>
    </details>
  </section>;
}
