"use client";

import Link from "next/link";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { InvoiceQuestions } from "@/components/InvoiceQuestions";
import { SessionFallback } from "@/components/SessionFallback";
import type { components } from "@/lib/schema";
import { useWorkspace, useWorkspaceSummary } from "@/lib/use-workspace";

type CategoryCount = components["schemas"]["CategoryCount"];
type DefinedCategory = CategoryCount & { id: string };

// The summary lists "Uncategorized" with a null id; only real categories can scope a question.
function isDefinedCategory(item: CategoryCount): item is DefinedCategory {
  return typeof item.id === "string";
}

export default function InsightsPage() {
  const session = useWorkspace();
  const summary = useWorkspaceSummary(session.data?.org_id, session.data?.user_id);
  const [category, setCategory] = useState("");
  if (session.isError || !session.data) return <SessionFallback session={session} />;
  const data = summary.data;
  return <AppShell session={session.data} active="insights"><div className="mx-auto max-w-6xl space-y-6">
    <header><p className="eyebrow">Invoice intelligence</p><h1 className="mt-2 text-4xl font-bold tracking-tight">Workspace insights</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">Live totals across every invoice you can access. Amounts stay in their original currency and only count after human verification.</p></header>
    {summary.isPending && <p role="status" className="card p-6">Loading current totals…</p>}
    {summary.isError && <p role="alert" className="card p-6 text-rose-700">{summary.error.message} <button className="underline" onClick={() => summary.refetch()}>Try again</button></p>}
    {data && <>
      <div className="grid gap-4 sm:grid-cols-3">{[{ label: "Accessible invoices", value: data.total_documents, detail: "Across your entire workspace" }, { label: "Ready for review", value: data.status_counts.needs_review ?? 0, detail: "Waiting for a human decision" }, { label: "Amounts not yet verified", value: data.excluded_amount_count, detail: "Excluded from currency totals" }].map(item => <section key={item.label} className="card p-5"><h2 className="text-xs font-semibold text-slate-500">{item.label}</h2><p className="mt-3 text-3xl font-bold">{item.value}</p><p className="mt-2 text-xs text-slate-400">{item.detail}</p></section>)}</div>
      <section className="card overflow-hidden"><div className="border-b border-slate-100 p-5"><h2 className="font-bold">Verified amounts by currency</h2><p className="mt-1 text-xs text-slate-500">These are workflow totals, not paid balances or an accounting ledger.</p></div>{data.amounts_by_currency.length === 0 ? <p className="p-6 text-sm text-slate-500">No verified amounts yet. Open an invoice and save its verified amount and currency.</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr>{["Currency", "Total", "Needs review", "Approved", "Rejected"].map(label => <th scope="col" className="whitespace-nowrap px-5 py-3 font-semibold" key={label}>{label}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{data.amounts_by_currency.map(row => <tr key={row.currency}><th scope="row" className="px-5 py-4 text-cyan-900">{row.currency}</th><td className="px-5 py-4 font-bold tabular-nums">{row.total}</td><td className="px-5 py-4 tabular-nums text-amber-800">{row.pending_review}</td><td className="px-5 py-4 tabular-nums text-emerald-800">{row.approved}</td><td className="px-5 py-4 tabular-nums text-rose-800">{row.rejected}</td></tr>)}</tbody></table></div>}</section>
      <div className="grid gap-5 lg:grid-cols-[1fr_2fr]"><section className="card self-start p-5"><div className="flex items-center justify-between gap-3"><h2 className="font-bold">Categories</h2>{session.data.role === "admin" && <Link href="/admin" className="text-xs font-semibold text-cyan-800 underline">Manage</Link>}</div><p className="mt-1 text-xs leading-5 text-slate-500">Organize invoices with categories defined by your admin.</p><div className="mt-5 space-y-4">{data.categories.map(item => <div key={item.id ?? "uncategorized"}><div className="flex justify-between gap-2 text-xs"><span className="font-semibold">{item.name}</span><span className="tabular-nums text-slate-500">{item.document_count}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-cyan-600" style={{ width: `${data.total_documents ? item.document_count / data.total_documents * 100 : 0}%` }} /></div></div>)}</div></section>
        <div className="space-y-3"><label className="block text-xs font-semibold">Question scope<select className="field mt-1 text-sm" value={category} onChange={event => setCategory(event.target.value)}><option value="">All accessible invoices</option>{data.categories.filter(isDefinedCategory).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><InvoiceQuestions key={category} categoryId={category || undefined} /></div>
      </div>
    </>}
  </div></AppShell>;
}
