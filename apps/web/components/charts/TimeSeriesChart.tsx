"use client";

import { useId } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CHART_SERIES, isChartSeriesKey, type ChartSeriesKey, type SeriesRow } from "@/lib/metrics";

type TimeSeriesChartProps = {
  /** Rows in day order; the `label` is what the axis shows. */
  rows: SeriesRow[];
  active: readonly ChartSeriesKey[];
  onToggle: (key: ChartSeriesKey) => void;
  /** "Documents per day over the last 30 days" */
  title: string;
  loading?: boolean;
};

type TooltipEntry = { dataKey?: unknown; value?: unknown };

function TooltipPanel({ active, payload, label }: { active?: boolean; payload?: readonly TooltipEntry[]; label?: unknown }) {
  if (!active || !payload || payload.length === 0) return null;
  return <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg">
    <p className="font-semibold text-slate-700">{String(label ?? "")}</p>
    <ul className="mt-1 space-y-1">
      {payload.map(entry => {
        const key = typeof entry.dataKey === "string" && isChartSeriesKey(entry.dataKey) ? entry.dataKey : null;
        const series = key ? CHART_SERIES.find(item => item.key === key) : undefined;
        if (!series) return null;
        return <li key={series.key} className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0.5 w-3 rounded" style={{ backgroundColor: series.color }} />
          <span className="font-bold tabular-nums text-slate-900">{typeof entry.value === "number" ? entry.value.toLocaleString("en-US") : String(entry.value ?? "")}</span>
          <span className="text-slate-500">{series.label}</span>
        </li>;
      })}
    </ul>
  </div>;
}

/**
 * Daily counts as 2px lines with a crosshair tooltip, series toggles above, and
 * a "Show data" table so every value is reachable without a pointer.
 */
export function TimeSeriesChart({ rows, active, onToggle, title, loading = false }: TimeSeriesChartProps) {
  const tableId = useId();
  const hasData = rows.length > 0 && rows.some(row => CHART_SERIES.some(series => row[series.key] > 0));
  const plotted = CHART_SERIES.filter(series => active.includes(series.key));

  return <div className="min-w-0">
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Series to plot">
      {CHART_SERIES.map(series => {
        const on = active.includes(series.key);
        return <button key={series.key} type="button" aria-pressed={on} onClick={() => onToggle(series.key)} title={series.description} className={`inline-flex min-h-9 items-center gap-2 rounded-full border px-3 text-xs font-semibold transition-colors ${on ? "border-slate-300 bg-white text-slate-800" : "border-transparent bg-slate-100 text-slate-500 hover:bg-slate-200"}`}>
          <span aria-hidden="true" className="inline-block h-1 w-4 rounded" style={{ backgroundColor: on ? series.color : "#cbd5e1" }} />
          {series.label}
        </button>;
      })}
    </div>

    <div role="figure" aria-label={title} aria-busy={loading || undefined} className="relative mt-4 h-64 w-full min-w-0 sm:h-72">
      {rows.length > 0 && <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 12, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} stroke="#e2e8f0" strokeWidth={1} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={{ stroke: "#e2e8f0" }} minTickGap={24} interval="preserveStartEnd" />
          <YAxis allowDecimals={false} width={36} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} tickFormatter={(value: number) => value.toLocaleString("en-US")} />
          <Tooltip content={<TooltipPanel />} cursor={{ stroke: "#94a3b8", strokeWidth: 1 }} isAnimationActive={false} />
          {plotted.map(series => <Line key={series.key} type="monotone" dataKey={series.key} name={series.label} stroke={series.color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" dot={rows.length <= 31 ? { r: 3, strokeWidth: 2, stroke: "#ffffff", fill: series.color } : false} activeDot={{ r: 5, strokeWidth: 2, stroke: "#ffffff" }} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>}
      {!hasData && <p role="status" className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 px-6 text-center text-sm text-slate-500">{loading ? "Loading activity…" : rows.length === 0 ? "No activity in this range yet." : "No activity in this range yet. Documents appear here as they are processed."}</p>}
    </div>

    <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2 text-xs">
      <summary className="cursor-pointer font-semibold text-slate-700">Show data</summary>
      <div className="mt-2 max-h-72 overflow-auto">
        <table id={tableId} className="w-full text-left">
          <caption className="sr-only">{title}, one row per day</caption>
          <thead><tr className="text-[10px] uppercase tracking-wide text-slate-400"><th scope="col" className="py-1 pr-3 font-semibold">Day</th>{CHART_SERIES.map(series => <th key={series.key} scope="col" className="py-1 pr-3 text-right font-semibold">{series.label}</th>)}</tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={CHART_SERIES.length + 1} className="py-2 text-slate-500">No days in this range.</td></tr>}
            {rows.map(row => <tr key={row.day} className="border-t border-slate-200"><th scope="row" className="py-1 pr-3 font-medium text-slate-600">{row.day}</th>{CHART_SERIES.map(series => <td key={series.key} className="py-1 pr-3 text-right tabular-nums text-slate-800">{row[series.key].toLocaleString("en-US")}</td>)}</tr>)}
          </tbody>
        </table>
      </div>
    </details>
  </div>;
}
