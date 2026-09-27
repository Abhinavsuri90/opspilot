"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { api } from "@/lib/api";
import { isUnauthorizedError, unauthorizedError } from "@/lib/errors";
import { useWorkspace } from "@/lib/use-workspace";

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metric(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function EvalsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const session = useWorkspace();
  const isAdmin = session.data?.role === "admin";
  const report = useQuery({
    queryKey: ["latest-eval", session.data?.user_id],
    enabled: isAdmin,
    queryFn: async () => {
      const result = await api.GET("/v1/evals/latest");
      if (result.response.status === 401) throw unauthorizedError();
      if (result.response.status === 404) return null;
      if (result.error || !result.data) throw new Error("Could not load the latest evaluation.");
      return result.data;
    },
  });
  useEffect(() => {
    if (isUnauthorizedError(report.error)) { client.clear(); router.replace("/login"); }
  }, [report.error, client, router]);

  if (session.isError || !session.data || isUnauthorizedError(report.error)) return <SessionFallback session={session} />;
  if (!isAdmin) return <AppShell session={session.data} active="evals"><AdminOnly description="Only organization administrators can view the quality report." /></AppShell>;

  const data = report.data;
  const cost = data?.cost;
  const learning = data?.learning;
  const deltas = learning?.deltas;
  const exactDelta = deltas && typeof deltas === "object" && !Array.isArray(deltas) ? number((deltas as Record<string, unknown>).exact_match) : null;
  const cards = data ? [
    ["Exact field match", data.exact_match, "Synthetic ground-truth fields matched exactly"],
    ["Grounded evidence", data.grounded_fraction, "Extracted fields linked to source text"],
    ["Flag precision", data.flag_precision, "Flagged cases that actually needed attention"],
    ["Flag recall", data.flag_recall, "Problem cases the evaluator flagged"],
    ["Document type", data.type_detection, "Synthetic documents assigned the correct type"],
    ["Escalation", data.escalation_rate, "Cases sent to the second model"],
  ] as const : [];

  return <AppShell session={session.data} active="evals">
    <p className="text-[11px] font-bold uppercase tracking-[.18em] text-cyan-700">Operator evaluation</p>
    <h1 className="mt-2 text-3xl font-bold tracking-[-.04em] text-[#12233d] sm:text-[38px]">Quality lab</h1>
    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Results from a local synthetic-document evaluation. They describe the tested model and data set, not the quality of your organization&apos;s invoices. Reviewer edits are tracked separately on the Dashboard.</p>
    {report.isPending && <p role="status" className="mt-6 text-sm text-slate-500">Loading the latest report…</p>}
    {report.isError && <p role="alert" className="mt-6 rounded-xl bg-rose-50 p-4 text-sm text-rose-800">Could not load the report. <button type="button" className="font-semibold underline" onClick={() => report.refetch()}>Try again</button></p>}
    {report.isSuccess && !data && <div className="card mt-6 p-6"><h2 className="font-bold text-slate-900">No evaluation run yet</h2><p className="mt-2 text-sm text-slate-600">From the project directory, run <code className="rounded bg-slate-100 px-1.5 py-0.5">make eval</code>. Then refresh this page. The standard run uses deterministic rules and does not need an API key.</p></div>}
    {data && <>
      <div className="card mt-6 p-5"><h2 className="font-bold text-slate-900">Latest run</h2><dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4"><div><dt className="text-xs text-slate-500">Run time (UTC)</dt><dd className="mt-1 font-semibold">{data.generated_at}</dd></div><div><dt className="text-xs text-slate-500">Provider / model</dt><dd className="mt-1 break-words font-semibold">{data.provider} / {data.model}</dd></div><div><dt className="text-xs text-slate-500">Second model</dt><dd className="mt-1 break-words font-semibold">{data.tier2_model ?? "None"}</dd></div><div><dt className="text-xs text-slate-500">Test set</dt><dd className="mt-1 font-semibold">{data.dataset}</dd></div></dl></div>
      <section aria-labelledby="eval-results-heading" className="mt-6"><h2 id="eval-results-heading" className="text-lg font-bold text-[#12233d]">Measured results</h2><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{cards.map(([label, value, help]) => <div key={label} className="card p-5"><p className="text-xs font-semibold text-slate-500">{label}</p><p className="mt-2 text-3xl font-bold text-[#12233d]">{metric(value)}</p><p className="mt-2 text-xs leading-5 text-slate-600">{help}</p></div>)}</div></section>
      <section aria-label="Learning and model cost" className="mt-6 grid gap-4 lg:grid-cols-2"><div className="card p-5"><h2 className="font-bold text-slate-900">Learning check</h2><p className="mt-2 text-sm text-slate-600">The evaluator compares held-out documents before and after adding reviewed examples to memory.</p><p className="mt-4 text-2xl font-bold text-[#12233d]">{exactDelta === null ? "—" : `${exactDelta >= 0 ? "+" : ""}${(exactDelta * 100).toFixed(1)} percentage points`}</p><p className="mt-1 text-xs text-slate-500">Exact-match change on the held-out set. Zero means this run found no improvement; it is not evidence of learning gains.</p></div><div className="card p-5"><h2 className="font-bold text-slate-900">Model calls</h2><p className="mt-4 text-2xl font-bold text-[#12233d]">{number(cost?.calls)?.toLocaleString("en-US") ?? "—"}</p><p className="mt-1 text-sm text-slate-600">Estimated spend: {number(cost?.cost_cents_total)?.toFixed(3) ?? "—"} US cents · unpriced calls: {number(cost?.unpriced_calls)?.toLocaleString("en-US") ?? "—"}</p><p className="mt-2 text-xs text-slate-500">These figures use a local price table and exclude the learning comparison calls.</p></div></section>
      <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"><strong>What this report does not prove.</strong> {data.limitations}</div>
    </>}
  </AppShell>;
}
