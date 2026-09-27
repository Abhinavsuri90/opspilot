"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { api } from "@/lib/api";
import { countInProgress, documentStatusLabel, documentStatusTone, isDocumentInProgress, type DocumentStatusTone } from "@/lib/document-status";
import { isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { useWorkspace, useWorkspaceSummary } from "@/lib/use-workspace";

const pillTones: Record<DocumentStatusTone, string> = {
  review: "bg-amber-50 text-amber-800 ring-amber-200",
  failed: "bg-rose-50 text-rose-800 ring-rose-200",
  progress: "bg-sky-50 text-sky-800 ring-sky-200",
  completed: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  rejected: "bg-slate-100 text-slate-600 ring-slate-200",
  neutral: "bg-slate-50 text-slate-700 ring-slate-200",
};

export default function DashboardPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useWorkspace();
  const summary = useWorkspaceSummary(session.data?.org_id, session.data?.user_id);
  const documents = useQuery({
    queryKey: ["documents", session.data?.user_id, session.data?.org_id],
    enabled: Boolean(session.data),
    queryFn: async () => {
      const result = await api.GET("/v1/documents");
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load documents");
      return result.data;
    },
    refetchInterval: query => query.state.data?.some(item => isDocumentInProgress(item.status)) ? 2000 : 15000,
  });

  useEffect(() => {
    if (isUnauthorizedError(documents.error)) {
      queryClient.clear();
      router.replace("/login");
    }
  }, [documents.error, queryClient, router]);

  if (session.isError || !session.data || isUnauthorizedError(documents.error)) return <SessionFallback session={session} />;

  const recent = documents.data ?? [];
  const metrics = [
    { label: "Accessible invoices", value: summary.data?.total_documents ?? 0, detail: "Across your entire workspace", color: "bg-sky-100 text-sky-700", icon: "▤" },
    { label: "Needs review", value: summary.data?.status_counts.needs_review ?? 0, detail: "Fields ready to inspect", color: "bg-amber-100 text-amber-700", icon: "◷" },
    { label: "In progress", value: countInProgress(summary.data?.status_counts), detail: "Queued, extracting or validating", color: "bg-cyan-100 text-cyan-700", icon: "↗" },
    { label: "Auto-approved", value: summary.data?.status_counts.auto_approved ?? 0, detail: "Approved by policy, no reviewer needed", color: "bg-emerald-100 text-emerald-700", icon: "✓" },
    { label: "Failed", value: summary.data?.status_counts.failed ?? 0, detail: "May be eligible to retry", color: "bg-rose-100 text-rose-700", icon: "!" },
  ];

  return <AppShell session={session.data} active="dashboard">
    <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[.18em] text-cyan-700">Operations overview</p>
        <h1 className="mt-2 text-3xl font-bold tracking-[-.04em] text-[#12233d] sm:text-[38px]">Dashboard</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">Monitor invoice intake and open the records that need attention.</p>
      </div>
      <Link href="/inbox" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#15395e] px-5 text-sm font-semibold text-white shadow-[0_8px_18px_rgba(21,57,94,.15)] transition-colors hover:bg-[#0d2c4d]">
        Open inbox <span aria-hidden="true">↗</span>
      </Link>
    </div>

    <section aria-label="Workflow introduction" className="relative isolate overflow-hidden rounded-[22px] bg-[#123757] px-6 py-7 text-white shadow-[0_16px_36px_rgba(13,32,57,.12)] sm:px-8 sm:py-8">
      <div aria-hidden="true" className="pointer-events-none absolute -right-10 -top-16 -z-10 h-64 w-64 rounded-full border-[34px] border-cyan-300/10" />
      <div aria-hidden="true" className="pointer-events-none absolute bottom-[-110px] right-48 -z-10 h-52 w-52 rounded-full border-[24px] border-white/5" />
      <p className="text-[11px] font-bold uppercase tracking-[.18em] text-cyan-200">Invoice workflow</p>
      <h2 className="mt-3 max-w-2xl text-2xl font-semibold tracking-[-.03em] sm:text-[30px]">A clear path from invoice to approval.</h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-200">Upload an invoice, inspect its source evidence, and collaborate with your reviewers. Track decisions and verified amounts from one workspace.</p>
      <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-xs font-medium text-cyan-100"><span>01 · Upload</span><span>02 · Extract</span><span>03 · Review together</span><span>04 · Approve</span></div>
    </section>

    {summary.isError && <p role="alert" className="mt-4 text-sm text-rose-700">Could not load workspace totals. <button onClick={() => summary.refetch()} className="underline">Try again</button></p>}
    <section aria-label="Document summary" className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {metrics.map(metric => <div key={metric.label} className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_6px_20px_rgba(15,23,42,.035)]">
        <div className="flex items-start justify-between gap-2"><p className="text-xs font-semibold text-slate-600">{metric.label}</p><span aria-hidden="true" className={`grid h-8 w-8 place-items-center rounded-lg text-lg font-bold ${metric.color}`}>{metric.icon}</span></div>
        <p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{!summary.data ? <span className="text-slate-300">—</span> : metric.value}</p>
        <p className="mt-2 text-xs text-slate-500">{metric.detail}</p>
      </div>)}
    </section>

    <section aria-labelledby="recent-documents-heading" className="mt-6 overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_6px_20px_rgba(15,23,42,.035)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-5 sm:px-6">
        <div><h2 id="recent-documents-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Recent documents</h2><p className="mt-1 text-xs text-slate-500">The most recent invoices in this workspace, up to 50.</p></div>
        <Link href="/inbox" className="text-sm font-semibold text-[#11627a] hover:underline">View inbox <span aria-hidden="true">→</span></Link>
      </div>
      {documents.isPending && <p role="status" className="px-6 py-12 text-center text-sm text-slate-500">Loading documents…</p>}
      {documents.isError && <div className="px-6 py-8 text-sm text-rose-800" role="alert">Could not load documents. <button type="button" onClick={() => documents.refetch()} className="font-semibold underline">Try again</button></div>}
      {documents.isSuccess && recent.length === 0 && <div className="px-6 py-12 text-center"><div aria-hidden="true" className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-sky-50 text-2xl text-sky-700">▤</div><h3 className="mt-4 font-semibold text-slate-800">No documents yet</h3><p className="mt-1 text-sm text-slate-500">Upload your first invoice from the Inbox to start the workflow.</p><Link href="/inbox" className="mt-4 inline-block text-sm font-semibold text-[#11627a] hover:underline">Open inbox →</Link></div>}
      {documents.isSuccess && recent.length > 0 && <div className="divide-y divide-slate-100">
        {recent.slice(0, 6).map(item => <Link key={item.id} href={`/inbox?document=${encodeURIComponent(item.id)}`} className="group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-slate-50 sm:px-6">
          <span aria-hidden="true" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-sky-50 text-lg text-[#12617b]">▤</span>
          <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold text-slate-800 group-hover:text-[#11627a]">{item.filename}</span><span className="mt-0.5 block text-xs text-slate-500">{formatDateTime(item.created_at)}<span className="capitalize sm:hidden"> · {documentStatusLabel(item.status)}</span></span></span>
          <span className={`hidden rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ring-1 sm:inline-flex ${pillTones[documentStatusTone(item.status)]}`}>{documentStatusLabel(item.status)}</span>
          <span aria-hidden="true" className="text-slate-400 group-hover:text-[#11627a]">→</span>
        </Link>)}
      </div>}
    </section>
  </AppShell>;
}
