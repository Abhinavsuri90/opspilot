"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { useWorkspace, useWorkspaceSummary } from "@/lib/use-workspace";

export default function ReviewPage() {
  const session = useWorkspace();
  const [offset, setOffset] = useState(0);
  const summary = useWorkspaceSummary(session.data?.org_id, session.data?.user_id);
  const documents = useQuery({ queryKey: ["review-documents", session.data?.user_id, session.data?.org_id, offset], enabled: Boolean(session.data), queryFn: async () => {
    const result = await api.GET("/v1/documents", { params: { query: { status: "needs_review", limit: 25, offset } } });
    if (!result.data || result.error) throw new Error("Could not load the review queue");
    return result.data;
  }, refetchInterval: 10000 });
  if (session.isError) return <main className="p-8"><p role="alert">{session.error.message}</p><button className="secondary mt-4" onClick={() => session.refetch()}>Try again</button></main>;
  if (!session.data) return <main className="p-8" role="status">Loading workspace…</main>;
  return <AppShell session={session.data} active="review"><div className="mx-auto max-w-6xl space-y-6">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">Human review</p><h1 className="mt-2 text-4xl font-bold tracking-tight">Review queue</h1><p className="mt-3 max-w-xl text-sm leading-6 text-slate-500">Inspect the full invoice, compare the extracted evidence and record a clear decision. Admins can assign reviewers from the invoice.</p></div><div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4"><p className="text-xs font-semibold text-amber-800">Awaiting review</p><p className="mt-1 text-3xl font-bold text-amber-950">{summary.data ? (summary.data.status_counts.needs_review ?? 0) : "—"}</p></div></header>
    {!["admin", "reviewer"].includes(session.data.role) && <p className="rounded-xl bg-blue-50 p-4 text-sm text-blue-900">You can inspect invoices you have access to. Review decisions require an admin or reviewer account.</p>}
    <section className="card overflow-hidden"><div className="flex flex-wrap justify-between gap-2 border-b border-slate-100 p-5"><h2 className="font-bold">Ready for a decision</h2><p className="text-xs text-slate-500">Updates every 10 seconds · most recent first</p></div>
      {documents.isPending && <p role="status" className="p-8 text-slate-500">Loading queue…</p>}
      {documents.isError && <p role="alert" className="p-6 text-rose-700">{documents.error.message} <button className="underline" onClick={() => documents.refetch()}>Try again</button></p>}
      {documents.data?.length === 0 && <div className="p-12 text-center"><div className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-emerald-50 text-2xl text-emerald-700">✓</div><h3 className="mt-4 text-lg font-bold">This queue is clear</h3><p className="mt-2 text-sm text-slate-500">Invoices appear here once extraction finishes.</p><Link href="/inbox" className="secondary mt-5">Open inbox</Link></div>}
      <div className="divide-y divide-slate-100">{documents.data?.map((item, index) => <Link href={`/inbox?document=${item.id}`} key={item.id} className="group flex items-center gap-4 p-5 hover:bg-cyan-50/40"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-sm font-bold text-slate-500">{offset + index + 1}</span><div className="min-w-0 flex-1"><h3 className="truncate text-sm font-bold group-hover:text-cyan-800">{item.filename}</h3><p className="mt-1 text-xs text-slate-500">Received {new Date(item.created_at).toLocaleString()} · {Math.ceil(item.size_bytes / 1024)} KB</p></div><span className="text-sm font-semibold text-cyan-800">Review →</span></Link>)}</div>
      <div className="flex items-center justify-between border-t border-slate-100 p-4"><button className="secondary text-xs" disabled={offset === 0 || documents.isFetching} onClick={() => setOffset(value => Math.max(0, value - 25))}>Previous</button><span className="text-xs text-slate-500">Page {offset / 25 + 1}</span><button className="secondary text-xs" disabled={!documents.data || documents.data.length < 25 || documents.isFetching} onClick={() => setOffset(value => value + 25)}>Next</button></div>
    </section>
  </div></AppShell>;
}
