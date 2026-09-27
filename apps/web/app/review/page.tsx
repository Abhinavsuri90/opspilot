"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { SlaChip } from "@/components/review/SlaChip";
import { api } from "@/lib/api";
import { isUnauthorizedError, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { AGE_OPTIONS, buildQueueQuery, DEFAULT_QUEUE_FILTERS, formatQueueTotal, QUEUE_PAGE_SIZE, queueFiltersActive, type QueueAge, type QueueAssigned, type QueueFilters } from "@/lib/review-queue";
import { useNow } from "@/lib/use-now";
import { useWorkspace, useWorkspaceSummary } from "@/lib/use-workspace";

const assignedOptions: { value: QueueAssigned; label: string }[] = [
  { value: "all", label: "Anyone" },
  { value: "me", label: "Assigned to me" },
  { value: "unassigned", label: "Unassigned" },
];

const columns = "lg:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,.9fr)_minmax(0,1.2fr)_minmax(0,1.4fr)_minmax(0,1.2fr)]";

function Cell({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return <span className={`min-w-0 ${className}`}><span className="block text-[10px] font-bold uppercase tracking-wide text-slate-400 lg:hidden">{label}</span>{children}</span>;
}

export default function ReviewQueuePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useWorkspace();
  const orgId = session.data?.org_id;
  const userId = session.data?.user_id;
  const ready = Boolean(session.data) && !session.isError;
  const [filters, setFilters] = useState<QueueFilters>(DEFAULT_QUEUE_FILTERS);
  const [vendorInput, setVendorInput] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [knownTypes, setKnownTypes] = useState<string[]>([]);
  const now = useNow(30_000);
  const summary = useWorkspaceSummary(orgId, userId);

  // Vendor typing is debounced; every other filter applies at once. Any change starts from page one.
  useEffect(() => {
    const next = vendorInput.trim();
    if (next === filters.vendor) return;
    const timer = setTimeout(() => { setFilters(current => ({ ...current, vendor: next })); setOffset(0); }, 300);
    return () => clearTimeout(timer);
  }, [vendorInput, filters.vendor]);

  const queue = useQuery({
    queryKey: ["review-queue", userId, orgId, filters, offset],
    enabled: ready,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const result = await api.GET("/v1/review/queue", { params: { query: buildQueueQuery(filters, offset) } });
      if (result.response.status === 401) throw unauthorizedError();
      if (!result.data || result.error) throw new Error("Could not load the review queue");
      return result.data;
    },
    refetchInterval: 10_000,
  });
  useEffect(() => {
    if (isUnauthorizedError(queue.error)) {
      queryClient.clear();
      router.replace("/login");
    }
  }, [queue.error, queryClient, router]);
  useEffect(() => {
    const seen = queue.data?.map(item => item.document_type) ?? [];
    setKnownTypes(current => {
      const merged = [...new Set([...current, ...seen])].sort();
      return merged.length === current.length && merged.every((type, index) => type === current[index]) ? current : merged;
    });
  }, [queue.data]);

  const rows = useMemo(() => overdueOnly ? (queue.data ?? []).filter(item => item.overdue) : queue.data ?? [], [queue.data, overdueOnly]);
  if (session.isError || !session.data || isUnauthorizedError(queue.error)) return <SessionFallback session={session} />;

  const canReview = session.data.role === "admin" || session.data.role === "reviewer";
  const filtersActive = queueFiltersActive(filters, overdueOnly);
  const showEmpty = queue.isSuccess && !queue.isPlaceholderData && rows.length === 0;
  const typeOptions = filters.documentType && !knownTypes.includes(filters.documentType) ? [...knownTypes, filters.documentType].sort() : knownTypes;

  function update(values: Partial<QueueFilters>) { setFilters(current => ({ ...current, ...values })); setOffset(0); }
  function clearFilters() { setFilters(DEFAULT_QUEUE_FILTERS); setVendorInput(""); setOverdueOnly(false); setOffset(0); }

  return <AppShell session={session.data} active="review"><div className="mx-auto max-w-[1440px] space-y-6 pb-10">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="eyebrow">Human review</p><h1 className="mt-2 text-3xl font-bold tracking-tight md:text-4xl">Review queue</h1><p className="mt-3 max-w-xl text-sm leading-6 text-slate-500">Invoices waiting for a decision, soonest deadline first. Open one to check each field against the PDF and approve or reject it.</p></div>
      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4"><p className="text-xs font-semibold text-amber-800">Awaiting review</p><p className="mt-1 text-3xl font-bold text-amber-950">{summary.data ? (summary.data.status_counts.needs_review ?? 0) : "—"}</p></div>
    </header>
    {!canReview && <p className="rounded-xl bg-blue-50 p-4 text-sm text-blue-900">You can inspect invoices you have access to. Review decisions require an admin or reviewer account.</p>}

    <section className="card overflow-hidden" aria-label="Review queue">
      <form className="grid gap-3 border-b border-slate-100 p-5 sm:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_auto] xl:items-end" onSubmit={event => event.preventDefault()} aria-label="Queue filters">
        <label className="text-xs font-semibold text-slate-700">Document type
          <select className="field mt-1 text-sm" value={filters.documentType} onChange={event => update({ documentType: event.target.value })}>
            <option value="">All types</option>
            {typeOptions.map(type => <option key={type} value={type}>{type.replaceAll("_", " ")}</option>)}
          </select>
        </label>
        <label className="text-xs font-semibold text-slate-700">Vendor
          <input type="search" className="field mt-1 text-sm" placeholder="Search by vendor" value={vendorInput} onChange={event => setVendorInput(event.target.value)} maxLength={200} />
        </label>
        <label className="text-xs font-semibold text-slate-700">Received in last
          <select className="field mt-1 text-sm" value={filters.age} onChange={event => update({ age: event.target.value as QueueAge })}>
            {AGE_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="text-xs font-semibold text-slate-700">Assigned to
          <select className="field mt-1 text-sm" value={filters.assigned} onChange={event => update({ assigned: event.target.value as QueueAssigned })}>
            {assignedOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <div className="flex items-center gap-3 pb-2">
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-700"><input type="checkbox" checked={overdueOnly} onChange={event => setOverdueOnly(event.target.checked)} />Overdue only</label>
          {filtersActive && <button type="button" className="text-xs font-semibold text-blue-700 underline" onClick={clearFilters}>Clear</button>}
        </div>
      </form>
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-xs text-slate-500"><span>{rows.length} on this page{overdueOnly && queue.data ? ` · ${queue.data.length - rows.length} hidden by the overdue filter` : ""}</span><span>Updates every 10 seconds</span></div>

      {queue.isPending && <p role="status" className="p-8 text-sm text-slate-500">Loading queue…</p>}
      {queue.isError && <p role="alert" className="p-6 text-sm text-rose-700">{queue.error.message} <button type="button" className="underline" onClick={() => queue.refetch()}>Try again</button></p>}
      {showEmpty && (filtersActive
        ? <div className="p-12 text-center"><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-2xl text-slate-500" aria-hidden="true">⌕</div><h3 className="mt-4 text-lg font-bold">No invoices match these filters.</h3><p className="mt-2 text-sm text-slate-500">Try another vendor, type, age or assignee{offset > 0 ? ", or return to the first page" : ""}.</p><button type="button" className="secondary mt-5 text-xs" onClick={clearFilters}>Clear filters</button></div>
        : <div className="p-12 text-center"><div className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-emerald-50 text-2xl text-emerald-700" aria-hidden="true">✓</div><h3 className="mt-4 text-lg font-bold">This queue is clear</h3><p className="mt-2 text-sm text-slate-500">Invoices appear here once extraction finishes and a decision is needed.</p><Link href="/inbox" className="secondary mt-5">Open inbox</Link></div>)}

      {rows.length > 0 && <div aria-busy={queue.isPlaceholderData} className={`transition-opacity ${queue.isPlaceholderData ? "opacity-60" : ""}`}>
        <div aria-hidden="true" className={`hidden gap-4 border-y border-slate-100 bg-slate-50 px-5 py-2 text-[11px] font-bold uppercase tracking-wide text-slate-500 lg:grid ${columns}`}><span>File</span><span>Vendor</span><span>Total</span><span>Flagged</span><span>SLA</span><span>Assignee</span><span>Opened</span></div>
        <ul aria-label="Invoices awaiting review" className="divide-y divide-slate-100">
        {rows.map(item => <li key={item.document_id}><Link href={`/review/${encodeURIComponent(item.document_id)}`} aria-label={`Review ${item.filename}`} className={`grid grid-cols-2 gap-x-4 gap-y-3 px-5 py-4 text-sm transition-colors hover:bg-cyan-50/50 focus-visible:bg-cyan-50/50 lg:items-center lg:gap-4 ${columns}`}>
          <Cell label="File" className="col-span-2 lg:col-span-1"><span className="block break-all font-bold text-slate-900">{item.filename}</span><span className="block text-xs capitalize text-slate-500">{item.document_type.replaceAll("_", " ")}</span></Cell>
          <Cell label="Vendor"><span className="block truncate text-slate-800">{item.vendor ?? <span className="text-slate-400">Unknown</span>}</span></Cell>
          <Cell label="Total"><span className="tabular-nums text-slate-800">{formatQueueTotal(item.total, item.currency)}</span></Cell>
          <Cell label="Flagged"><span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-bold ${item.flagged_count > 0 ? "border-amber-300 bg-amber-50 text-amber-900" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{item.flagged_count} flagged</span></Cell>
          <Cell label="SLA"><SlaChip dueAt={item.due_at} now={now} /></Cell>
          <Cell label="Assignee"><span className="block truncate text-slate-700">{item.assigned_reviewer_email ?? <span className="text-slate-400">Unassigned</span>}</span></Cell>
          <Cell label="Opened"><span className="text-xs text-slate-600">{item.opened_at ? formatDateTime(item.opened_at) : formatDateTime(item.created_at)}</span></Cell>
        </Link></li>)}
        </ul>
      </div>}
      <div className="flex items-center justify-between gap-3 border-t border-slate-100 p-4"><button type="button" className="secondary text-xs" disabled={offset === 0 || queue.isFetching} onClick={() => setOffset(value => Math.max(0, value - QUEUE_PAGE_SIZE))}>Previous</button><span className="text-xs text-slate-500">Page {offset / QUEUE_PAGE_SIZE + 1}</span><button type="button" className="secondary text-xs" disabled={!queue.data || queue.data.length < QUEUE_PAGE_SIZE || queue.isFetching} onClick={() => setOffset(value => value + QUEUE_PAGE_SIZE)}>Next</button></div>
    </section>
  </div></AppShell>;
}
