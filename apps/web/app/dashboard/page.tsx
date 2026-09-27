"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DocumentSourceBadge } from "@/components/DocumentSourceBadge";
import { SessionFallback } from "@/components/SessionFallback";
import { AccuracyChart } from "@/components/charts/AccuracyChart";
import { KpiTiles } from "@/components/charts/KpiTile";
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import { ACTIONS_POLL_MS } from "@/lib/actions";
import { api } from "@/lib/api";
import { documentStatusLabel, documentStatusTone, isDocumentInProgress, type DocumentStatusTone } from "@/lib/document-status";
import { documentTypeLabel, knownDocumentTypes } from "@/lib/document-types";
import { isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { CHART_SERIES, DEFAULT_METRIC_RANGE, METRIC_RANGES, METRICS_POLL_MS, isMetricRange, kpiDefinitions, kpiTiles, seriesRows, toggleSeries, type ChartSeriesKey, type MetricRange } from "@/lib/metrics";
import { useWorkspace } from "@/lib/use-workspace";

const pillTones: Record<DocumentStatusTone, string> = {
  review: "bg-amber-50 text-amber-800 ring-amber-200",
  failed: "bg-rose-50 text-rose-800 ring-rose-200",
  progress: "bg-sky-50 text-sky-800 ring-sky-200",
  actions: "bg-orange-50 text-orange-800 ring-orange-200",
  completed: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  rejected: "bg-slate-100 text-slate-600 ring-slate-200",
  neutral: "bg-slate-50 text-slate-700 ring-slate-200",
};

const ALL_SERIES: ChartSeriesKey[] = CHART_SERIES.map(series => series.key);

export default function DashboardPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useWorkspace();
  const orgId = session.data?.org_id;
  const userId = session.data?.user_id;
  const ready = Boolean(session.data);
  const [days, setDays] = useState<MetricRange>(DEFAULT_METRIC_RANGE);
  const [documentType, setDocumentType] = useState("");
  const [activeSeries, setActiveSeries] = useState<ChartSeriesKey[]>(ALL_SERIES);

  // The most recent 100 documents feed both the recent list and the type filter.
  const documents = useQuery({
    queryKey: ["documents", userId, orgId, "dashboard"],
    enabled: ready,
    queryFn: async () => {
      const result = await api.GET("/v1/documents", { params: { query: { limit: 100 } } });
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load documents");
      return result.data;
    },
    refetchInterval: query => query.state.data?.some(item => isDocumentInProgress(item.status)) ? 2000 : 15000,
  });

  const metrics = useQuery({
    queryKey: ["metrics", orgId, userId, days, documentType],
    enabled: ready,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const result = await api.GET("/v1/metrics/overview", { params: { query: { days, document_type: documentType || undefined } } });
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load the KPIs");
      return result.data;
    },
    refetchInterval: METRICS_POLL_MS,
  });

  const actions = useQuery({
    queryKey: ["actions-summary", orgId, userId],
    enabled: ready,
    queryFn: async () => {
      const result = await api.GET("/v1/actions/summary");
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load action counts");
      return result.data;
    },
    refetchInterval: ACTIONS_POLL_MS,
  });

  const accuracy = useQuery({
    queryKey: ["accuracy", orgId, userId, documentType],
    enabled: ready,
    queryFn: async () => {
      const result = await api.GET("/v1/metrics/accuracy", { params: { query: { weeks: 12, document_type: documentType || undefined } } });
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load weekly accuracy");
      return result.data;
    },
    refetchInterval: METRICS_POLL_MS,
  });

  useEffect(() => {
    if (isUnauthorizedError(documents.error) || isUnauthorizedError(metrics.error) || isUnauthorizedError(actions.error) || isUnauthorizedError(accuracy.error)) {
      queryClient.clear();
      router.replace("/login");
    }
  }, [documents.error, metrics.error, actions.error, accuracy.error, queryClient, router]);

  if (session.isError || !session.data || isUnauthorizedError(documents.error) || isUnauthorizedError(metrics.error)) return <SessionFallback session={session} />;

  const recent = documents.data ?? [];
  const typeOptions = knownDocumentTypes(recent);
  const typeChoices = documentType && !typeOptions.includes(documentType) ? [...typeOptions, documentType] : typeOptions;
  const overview = metrics.data;
  const tiles = kpiTiles(overview);
  const rows = seriesRows(overview?.series ?? []);
  const rangeTitle = `${documentTypeLabel(documentType || "document")}s per day over the last ${days} days`;

  return <AppShell session={session.data} active="dashboard">
    <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[.18em] text-cyan-700">Operations overview</p>
        <h1 className="mt-2 text-3xl font-bold tracking-[-.04em] text-[#12233d] sm:text-[38px]">Dashboard</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">How the workspace is performing, and the records that need attention. <Link href="/guide" className="font-semibold text-[#11627a] underline-offset-2 hover:underline">New here? Follow the guide →</Link></p>
      </div>
      <Link href="/inbox" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#15395e] px-5 text-sm font-semibold text-white shadow-[0_8px_18px_rgba(21,57,94,.15)] transition-colors hover:bg-[#0d2c4d]">
        Open inbox <span aria-hidden="true">↗</span>
      </Link>
    </div>

    <form className="flex flex-wrap items-end gap-3" aria-label="KPI filters" onSubmit={event => event.preventDefault()}>
      <div role="group" aria-label="Range" className="flex rounded-xl bg-slate-100 p-1">
        {METRIC_RANGES.map(option => <button key={option} type="button" aria-pressed={days === option} onClick={() => { if (isMetricRange(option)) setDays(option); }} className={`min-h-9 rounded-lg px-3 text-xs font-semibold transition-colors ${days === option ? "bg-white text-[#12233d] shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>{option} days</button>)}
      </div>
      <label className="text-xs font-semibold text-slate-700">Document type
        <select className="field mt-1 !min-w-[180px] !py-2 text-sm" value={documentType} onChange={event => setDocumentType(event.target.value)}>
          <option value="">All types</option>
          {typeChoices.map(type => <option key={type} value={type}>{documentTypeLabel(type)}</option>)}
        </select>
      </label>
      {overview && <p className="pb-2 text-xs text-slate-500">{overview.range.start} to {overview.range.end}{metrics.isPlaceholderData ? " · updating…" : ""}</p>}
    </form>

    <section aria-label="Key performance indicators" className="mt-4">
      {metrics.isError && !isUnauthorizedError(metrics.error) && <p role="alert" className="mb-3 text-sm text-rose-700">Could not load the KPIs. <button type="button" onClick={() => metrics.refetch()} className="font-semibold underline">Try again</button></p>}
      <KpiTiles tiles={tiles} loading={metrics.isPending || metrics.isPlaceholderData} />
      <details className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm">
        <summary className="cursor-pointer font-semibold text-slate-700">What these numbers mean</summary>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          {kpiDefinitions().map(item => <div key={item.id}><dt className="text-xs font-bold text-slate-800">{item.label}</dt><dd className="mt-0.5 text-xs leading-5 text-slate-600">{item.definition}</dd></div>)}
        </dl>
        <p className="mt-3 text-xs text-slate-500">All KPIs cover the documents you can access. Range and document type filter every tile except the review queue depth, which is live.</p>
      </details>
    </section>

    {overview && <section aria-label="Model usage" className="mt-4 flex flex-wrap gap-x-6 gap-y-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600">
      <span><strong className="text-slate-800">{overview.llm_calls.toLocaleString("en-US")}</strong> model calls</span>
      <span><strong className="text-slate-800">{overview.cost_total_cents.toFixed(3)}¢</strong> estimated priced spend</span>
      <span><strong className="text-slate-800">{overview.tokens_in.toLocaleString("en-US")} / {overview.tokens_out.toLocaleString("en-US")}</strong> input / output tokens</span>
      {overview.cost_unpriced_calls > 0 && <span className="font-semibold text-amber-800">{overview.cost_unpriced_calls} calls have no price estimate</span>}
    </section>}

    <section aria-labelledby="activity-heading" className="card mt-6 p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 id="activity-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Activity over time</h2><p className="mt-1 text-xs text-slate-500">Documents per day for the selected range and type. Toggle a series to compare fewer lines.</p></div>
      </div>
      <div className="mt-4">
        <TimeSeriesChart rows={rows} active={activeSeries} onToggle={key => setActiveSeries(current => toggleSeries(current, key))} title={rangeTitle} loading={metrics.isPending} />
      </div>
    </section>

    {accuracy.isError && !isUnauthorizedError(accuracy.error) && <p role="alert" className="mt-4 text-sm text-rose-700">Could not load weekly accuracy. <button type="button" onClick={() => accuracy.refetch()} className="font-semibold underline">Try again</button></p>}
    <AccuracyChart points={accuracy.data ?? []} loading={accuracy.isPending} />

    <section aria-label="Agent actions" className="mt-6 grid gap-3 sm:grid-cols-2">
      <Link href="/actions?tab=pending" className="group rounded-2xl border border-amber-200/80 bg-amber-50/60 p-5 shadow-[0_6px_20px_rgba(15,23,42,.035)] transition-colors hover:bg-amber-50" data-testid="tile-pending-approvals">
        <div className="flex items-start justify-between gap-2"><p className="text-xs font-semibold text-amber-900">Pending approvals</p><span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-lg bg-amber-100 text-lg font-bold text-amber-700">⇢</span></div>
        <p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{actions.data ? actions.data.pending_approvals.toLocaleString("en-US") : <span className="text-slate-300">—</span>}</p>
        <p className="mt-2 text-xs text-amber-900">Actions waiting for a reviewer before anything leaves the system →</p>
      </Link>
      <Link href="/actions?tab=dead" className="group rounded-2xl border border-rose-200/80 bg-rose-50/60 p-5 shadow-[0_6px_20px_rgba(15,23,42,.035)] transition-colors hover:bg-rose-50" data-testid="tile-dead-letters">
        <div className="flex items-start justify-between gap-2"><p className="text-xs font-semibold text-rose-900">Dead letters</p><span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-lg bg-rose-100 text-lg font-bold text-rose-700">!</span></div>
        <p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{actions.data ? actions.data.dead_letters.toLocaleString("en-US") : <span className="text-slate-300">—</span>}</p>
        <p className="mt-2 text-xs text-rose-900">Actions the worker gave up on; open to retry →</p>
      </Link>
    </section>
    {actions.isError && !isUnauthorizedError(actions.error) && <p role="alert" className="mt-2 text-xs text-rose-700">Could not load action counts. <button type="button" onClick={() => actions.refetch()} className="font-semibold underline">Try again</button></p>}

    <section aria-labelledby="recent-documents-heading" className="mt-6 overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_6px_20px_rgba(15,23,42,.035)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-5 sm:px-6">
        <div><h2 id="recent-documents-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Recent documents</h2><p className="mt-1 text-xs text-slate-500">The latest documents in this workspace, from any intake channel.</p></div>
        <Link href="/inbox" className="text-sm font-semibold text-[#11627a] hover:underline">View inbox <span aria-hidden="true">→</span></Link>
      </div>
      {documents.isPending && <p role="status" className="px-6 py-12 text-center text-sm text-slate-500">Loading documents…</p>}
      {documents.isError && <div className="px-6 py-8 text-sm text-rose-800" role="alert">Could not load documents. <button type="button" onClick={() => documents.refetch()} className="font-semibold underline">Try again</button></div>}
      {documents.isSuccess && recent.length === 0 && <div className="px-6 py-12 text-center"><div aria-hidden="true" className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-sky-50 text-2xl text-sky-700">▤</div><h3 className="mt-4 font-semibold text-slate-800">No documents yet</h3><p className="mt-1 text-sm text-slate-500">Upload your first document from the Inbox, or connect an email inbox or API key in Settings.</p><Link href="/inbox" className="mt-4 inline-block text-sm font-semibold text-[#11627a] hover:underline">Open inbox →</Link></div>}
      {documents.isSuccess && recent.length > 0 && <div className="divide-y divide-slate-100">
        {recent.slice(0, 6).map(item => <Link key={item.id} href={`/inbox?document=${encodeURIComponent(item.id)}`} className="group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-slate-50 sm:px-6">
          <span aria-hidden="true" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-sky-50 text-lg text-[#12617b]">▤</span>
          <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold text-slate-800 group-hover:text-[#11627a]">{item.filename}</span><span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500"><span>{formatDateTime(item.created_at)} · {documentTypeLabel(item.document_type)}</span><DocumentSourceBadge source={item.source} sourceRef={item.source_ref} /><span className="capitalize sm:hidden">{documentStatusLabel(item.status)}</span></span></span>
          <span className={`hidden rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ring-1 sm:inline-flex ${pillTones[documentStatusTone(item.status)]}`}>{documentStatusLabel(item.status)}</span>
          <span aria-hidden="true" className="text-slate-400 group-hover:text-[#11627a]">→</span>
        </Link>)}
      </div>}
    </section>
  </AppShell>;
}
