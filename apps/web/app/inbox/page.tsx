"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useReducer, useRef, useState, type DragEvent, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { DocumentSourceBadge } from "@/components/DocumentSourceBadge";
import { InvoiceWorkspace } from "@/components/InvoiceWorkspace";
import { NearDuplicateBanner } from "@/components/NearDuplicateBanner";
import { SessionFallback } from "@/components/SessionFallback";
import { StatusBadge } from "@/components/StatusBadge";
import { percent } from "@/components/review/ConfidenceBar";
import { FieldStatusChip } from "@/components/review/FieldStatusChip";
import { api } from "@/lib/api";
import { countInProgress, documentStatusLabel, isDocumentInProgress } from "@/lib/document-status";
import { DOCUMENT_SOURCES, documentSourceLabel, documentTypeLabel, isDocumentSource, knownDocumentTypes } from "@/lib/document-types";
import { summarizeFieldStatuses } from "@/lib/fields";
import { isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { classifyRetryFailure } from "@/lib/retry";
import { isUploading, pendingUploads, summarizeBatch, uploadBlocker, uploadFailureMessage, uploadQueueReducer, uploadStatusLabels, type UploadItem, type UploadStatus } from "@/lib/upload-queue";
import { useWorkspace, useWorkspaceSummary } from "@/lib/use-workspace";

type StatusFilter = "all" | "in_progress" | "needs_review" | "failed" | "approved" | "rejected";

const PAGE_SIZE = 50;

const statusFilters: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "in_progress", label: "In progress" },
  { value: "needs_review", label: "Needs review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "failed", label: "Failed" },
];

const uploadTones: Record<UploadStatus, string> = {
  queued: "bg-slate-100 text-slate-600",
  uploading: "bg-sky-50 text-sky-800",
  accepted: "bg-emerald-50 text-emerald-800",
  duplicate: "bg-amber-50 text-amber-800",
  failed: "bg-rose-50 text-rose-800",
};

function fileSize(bytes: number): string {
  return `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}

export default function InboxPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const deepLinkApplied = useRef(false);
  // File objects stay out of React state; the queue only tracks names and outcomes.
  const files = useRef(new Map<string, File>());
  const [queue, dispatch] = useReducer(uploadQueueReducer, []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [uploadMessage, setUploadMessage] = useState("");
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [retryResult, setRetryResult] = useState<{ id: string; error: boolean; message: string } | null>(null);
  const [exhaustedRetryIds, setExhaustedRetryIds] = useState<Set<string>>(() => new Set());
  const [search, setSearch] = useState("");
  const [serverSearch, setServerSearch] = useState("");
  const [category, setCategory] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);

  // The API filters the list. Typing is debounced, and every new search, filter
  // or page starts from a fresh selection so the detail pane matches the list.
  useEffect(() => {
    const next = search.trim();
    if (next === serverSearch) return;
    const timer = setTimeout(() => { setServerSearch(next); setOffset(0); setSelectedId(null); }, 300);
    return () => clearTimeout(timer);
  }, [search, serverSearch]);

  const session = useWorkspace();
  const orgId = session.data?.org_id;
  const userId = session.data?.user_id;
  const ready = Boolean(session.data) && !session.isError;

  const categories = useQuery({
    queryKey: ["categories", orgId, userId],
    enabled: ready,
    queryFn: async () => {
      const result = await api.GET("/v1/categories");
      if (!result.data || result.error) throw new Error("Could not load categories");
      return result.data;
    },
  });
  const documents = useQuery({
    queryKey: ["documents", userId, orgId, offset, category, serverSearch, statusFilter, typeFilter, sourceFilter],
    enabled: ready,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const result = await api.GET("/v1/documents", { params: { query: { offset, limit: PAGE_SIZE, category_id: category || undefined, q: serverSearch || undefined, status: statusFilter !== "all" ? statusFilter : undefined, document_type: typeFilter || undefined, source: sourceFilter || undefined } } });
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load documents");
      return result.data;
    },
    refetchInterval: query => query.state.data?.some(item => isDocumentInProgress(item.status)) ? 2000 : 15000,
  });
  const listInProgress = documents.data?.some(item => isDocumentInProgress(item.status)) ?? false;
  const summary = useWorkspaceSummary(orgId, userId, { refetchInterval: listInProgress ? 2000 : 15000 });
  const activeId: string | null = documents.isPlaceholderData ? selectedId : selectedId ?? documents.data?.[0]?.id ?? null;
  const detail = useQuery({
    queryKey: ["document", activeId, orgId, userId],
    enabled: Boolean(activeId) && ready,
    queryFn: async () => {
      if (!activeId) throw new Error("No document selected");
      const result = await api.GET("/v1/documents/{document_id}", {
        params: { path: { document_id: activeId } },
      });
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load document");
      return result.data;
    },
    // Poll quickly only while the loaded document is being processed. A request
    // that failed (missing or inaccessible document) is not retried on a timer.
    refetchInterval: query => {
      if (query.state.status === "error") return false;
      const status = query.state.data?.status;
      return status !== undefined && isDocumentInProgress(status) ? 2000 : 15000;
    },
  });
  useEffect(() => {
    if (isUnauthorizedError(documents.error) || isUnauthorizedError(detail.error)) {
      queryClient.clear();
      router.replace("/login");
    }
  }, [documents.error, detail.error, queryClient, router]);

  useEffect(() => {
    if (deepLinkApplied.current) return;
    const requestedId = new URLSearchParams(window.location.search).get("document");
    if (requestedId && /^[0-9a-f-]{36}$/i.test(requestedId)) {
      setSelectedId(requestedId);
      deepLinkApplied.current = true;
    }
  }, [documents.data]);

  // Types seen so far stay in the menu, so a filter never loses its own option.
  const [knownTypes, setKnownTypes] = useState<string[]>([]);
  useEffect(() => {
    if (!documents.data) return;
    const seen = knownDocumentTypes(documents.data);
    setKnownTypes(current => {
      const merged = knownDocumentTypes([...current, ...seen].map(document_type => ({ document_type })));
      return merged.length === current.length && merged.every((type, index) => type === current[index]) ? current : merged;
    });
  }, [documents.data]);

  const filtersActive = statusFilter !== "all" || category !== "" || serverSearch !== "" || typeFilter !== "" || sourceFilter !== "" || offset > 0;
  const pageCount = documents.data?.length ?? 0;
  const showEmptyState = documents.isSuccess && !documents.isPlaceholderData && documents.data.length === 0;
  const counts = summary.data ? {
    inProgress: countInProgress(summary.data.status_counts),
    needsReview: summary.data.status_counts.needs_review ?? 0,
    failed: summary.data.status_counts.failed ?? 0,
  } : null;
  const typeChoices = typeFilter && !knownTypes.includes(typeFilter) ? [...knownTypes, typeFilter] : knownTypes;
  const pending = pendingUploads(queue);
  const busy = uploading || isUploading(queue);

  function clearFilters() {
    setSearch("");
    setServerSearch("");
    setCategory("");
    setStatusFilter("all");
    setTypeFilter("");
    setSourceFilter("");
    setOffset(0);
    setSelectedId(null);
  }
  function selectStatus(value: StatusFilter) { setStatusFilter(value); setOffset(0); setSelectedId(null); }
  function selectCategory(value: string) { setCategory(value); setOffset(0); setSelectedId(null); }
  function selectType(value: string) { setTypeFilter(value); setOffset(0); setSelectedId(null); }
  function selectSource(value: string) { setSourceFilter(value); setOffset(0); setSelectedId(null); }
  function selectPage(value: number) { setOffset(Math.max(0, value)); setSelectedId(null); }

  function addFiles(list: FileList | File[]) {
    const picked = [...list];
    if (picked.length === 0) return;
    const entries = picked.map(file => {
      const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      files.current.set(id, file);
      return { id, name: file.name, size: file.size };
    });
    dispatch({ type: "add", files: entries });
    setError("");
    setUploadMessage("");
    if (fileInput.current) fileInput.current.value = "";
  }

  function acceptDroppedFiles(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  }

  function removeFromQueue(id: string) {
    dispatch({ type: "remove", id });
    files.current.delete(id);
  }

  /** Send every queued (or previously failed) file, one at a time, and report where each one landed. */
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || pending.length === 0) return;
    setUploading(true);
    setError("");
    setUploadMessage("");
    const results: UploadItem[] = [];
    let lastDocumentId: string | null = null;
    try {
      for (const item of pending) {
        const file = files.current.get(item.id);
        const blocker = file ? uploadBlocker(file) : "The file is no longer available; choose it again.";
        if (!file || blocker) {
          dispatch({ type: "failed", id: item.id, message: blocker ?? "The file is no longer available; choose it again." });
          results.push({ ...item, status: "failed", message: blocker, documentId: null });
          continue;
        }
        dispatch({ type: "start", id: item.id });
        try {
          const result = await api.POST("/v1/documents", {
            body: { file },
            bodySerializer(body) {
              const form = new FormData();
              form.set("file", body.file);
              return form;
            },
          });
          if (result.response.status === 401) {
            queryClient.clear();
            router.replace("/login");
            return;
          }
          if (result.error || !result.data) {
            const message = uploadFailureMessage(result.response.status);
            dispatch({ type: "failed", id: item.id, message });
            results.push({ ...item, status: "failed", message, documentId: null });
            continue;
          }
          dispatch({ type: "accepted", id: item.id, documentId: result.data.id, duplicate: result.data.duplicate });
          results.push({ ...item, status: result.data.duplicate ? "duplicate" : "accepted", message: null, documentId: result.data.id });
          lastDocumentId = result.data.id;
        } catch {
          const message = "Could not reach the API. Try again shortly.";
          dispatch({ type: "failed", id: item.id, message });
          results.push({ ...item, status: "failed", message, documentId: null });
        }
      }
      const outcome = summarizeBatch(results);
      if (outcome.status) setUploadMessage(outcome.status);
      if (outcome.alert) setError(outcome.alert);
      if (lastDocumentId) {
        setSelectedId(lastDocumentId);
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["documents"] }),
          queryClient.invalidateQueries({ queryKey: ["workspace-summary"] }),
        ]);
      }
    } finally {
      setUploading(false);
    }
  }

  async function retryFailedDocument() {
    const id = detail.data?.id;
    if (!id || detail.data?.status !== "failed" || retryingId || exhaustedRetryIds.has(id)) return;
    setRetryingId(id);
    setRetryResult(null);
    try {
      const result = await api.POST("/v1/documents/{document_id}/retry", {
        params: { path: { document_id: id } },
      });
      if (result.response.status === 401) {
        queryClient.clear();
        router.replace("/login");
        return;
      }
      if (result.error || !result.data) {
        const failure = classifyRetryFailure(result.response.status, result.error);
        setRetryResult({ id, error: true, message: failure.message });
        if (failure.limitReached) {
          setExhaustedRetryIds(previous => new Set(previous).add(id));
        }
        if (failure.refreshDocument) {
          await queryClient.invalidateQueries({ queryKey: ["document", id] });
        }
        return;
      }
      setRetryResult({ id, error: false, message: "Retry queued. The extraction result will update automatically." });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["documents"] }),
        queryClient.invalidateQueries({ queryKey: ["document", id] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-summary"] }),
      ]);
    } catch {
      setRetryResult({ id, error: true, message: "Could not reach the API. Please try again." });
    } finally {
      setRetryingId(null);
    }
  }

  if (session.isError || !session.data || isUnauthorizedError(documents.error) || isUnauthorizedError(detail.error)) {
    return <SessionFallback session={session} />;
  }
  const canUpload = session.data.role === "admin" || session.data.role === "reviewer" || session.data.role === "member";
  const uploadLabel = pending.length === 0 ? "Upload documents" : `Upload ${pending.length} ${pending.length === 1 ? "document" : "documents"}`;

  return <AppShell session={session.data} active="inbox">
    <div className="mx-auto max-w-[1440px] space-y-6 pb-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Document operations / Inbox</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 md:text-4xl">Document inbox</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">Upload text-layer PDFs, follow extraction, and inspect every field against its source text. Documents that arrive by email or through the API land here too.</p>
        </div>
        <div className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600">{session.data.org_name} workspace</div>
      </header>

      <div className="grid gap-3 sm:grid-cols-3" aria-label="Workspace document summary">
        <div className="card flex items-center gap-4 p-4"><span className="grid h-11 w-11 place-items-center rounded-xl bg-blue-50 text-xl text-blue-700" aria-hidden="true">↗</span><div><p className="text-xs font-semibold text-slate-500">In progress</p><p className="text-2xl font-bold text-slate-900">{counts ? counts.inProgress : <span className="text-slate-300">—</span>}</p></div></div>
        <div className="card flex items-center gap-4 p-4"><span className="grid h-11 w-11 place-items-center rounded-xl bg-amber-50 text-xl text-amber-700" aria-hidden="true">◎</span><div><p className="text-xs font-semibold text-slate-500">Needs review</p><p className="text-2xl font-bold text-slate-900">{counts ? counts.needsReview : <span className="text-slate-300">—</span>}</p></div></div>
        <div className="card flex items-center gap-4 p-4"><span className="grid h-11 w-11 place-items-center rounded-xl bg-rose-50 text-xl text-rose-700" aria-hidden="true">!</span><div><p className="text-xs font-semibold text-slate-500">Failed</p><p className="text-2xl font-bold text-slate-900">{counts ? counts.failed : <span className="text-slate-300">—</span>}</p></div></div>
      </div>
      <p className="-mt-4 text-xs text-slate-500">{summary.isError
        ? <>Workspace totals are unavailable right now. <button type="button" className="font-semibold underline" onClick={() => summary.refetch()}>Retry totals</button></>
        : "Counts cover every document you can access, across all pages and filters."}</p>

      {canUpload ? <form onSubmit={upload} className="card overflow-hidden" aria-labelledby="upload-heading">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-6">
          <div><h2 id="upload-heading" className="text-base font-bold text-slate-900">Add documents</h2><p className="mt-0.5 text-xs text-slate-500">PDF only · up to 10 MB each · text layer required · several files at once</p></div>
          <a href="/sample-invoice.pdf" download className="secondary text-sm">Download sample invoice</a>
        </div>
        <div className="grid gap-5 p-5 sm:p-6">
          <div onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={acceptDroppedFiles} data-testid="upload-dropzone" className={`rounded-2xl border-2 border-dashed p-4 transition-colors ${dragging ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-slate-50/60"}`}>
            <label htmlFor="document-files" className="mb-2 block text-sm font-semibold text-slate-800">Document PDFs</label>
            <input ref={fileInput} id="document-files" type="file" multiple accept="application/pdf,.pdf" disabled={busy} onChange={event => { if (event.target.files) addFiles(event.target.files); }} className="block w-full cursor-pointer text-sm text-slate-600 file:mr-4 file:rounded-lg file:border-0 file:bg-white file:px-3 file:py-2 file:font-semibold file:text-blue-700 hover:file:bg-blue-50" />
            <p className="mt-2 text-xs text-slate-500">Choose one or more files, or drag them here. Files upload one after another. Scanned PDFs need OCR and cannot be extracted yet.</p>
          </div>
          {queue.length > 0 && <ul aria-label="Upload queue" className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
            {queue.map(item => <li key={item.id} data-testid="upload-item" data-upload-status={item.status} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
              <span className="min-w-0 flex-1 break-all font-semibold text-slate-800">{item.name}<span className="ml-2 text-xs font-normal text-slate-500">{fileSize(item.size)}</span></span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${uploadTones[item.status]}`}>{uploadStatusLabels[item.status]}{item.status === "uploading" && "…"}</span>
              {item.documentId && <button type="button" className="text-xs font-semibold text-[#11627a] underline" onClick={() => { setSelectedId(item.documentId); setRetryResult(null); }}>Open</button>}
              {item.status !== "uploading" && <button type="button" aria-label={`Remove ${item.name} from the queue`} className="grid h-7 w-7 place-items-center rounded-lg text-slate-500 hover:bg-slate-100" onClick={() => removeFromQueue(item.id)}>×</button>}
              {item.message && <span className={`basis-full text-xs ${item.status === "failed" ? "text-rose-700" : "text-slate-500"}`}>{item.message}</span>}
            </li>)}
          </ul>}
          <div className="flex flex-wrap items-center gap-3">
            <button className="primary w-full sm:w-auto" disabled={pending.length === 0 || busy} type="submit">{busy ? "Uploading…" : uploadLabel}<span aria-hidden="true">→</span></button>
            {queue.some(item => item.status === "accepted" || item.status === "duplicate" || item.status === "failed") && !busy && <button type="button" className="secondary text-sm" onClick={() => { for (const item of queue) if (item.status !== "queued" && item.status !== "uploading") files.current.delete(item.id); dispatch({ type: "clear-finished" }); }}>Clear finished</button>}
          </div>
        </div>
      </form> : <p className="card p-5 text-sm text-slate-600">Your workspace role can view documents but cannot upload them.</p>}

      {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</p>}
      {uploadMessage && <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{uploadMessage}</p>}

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(320px,.9fr)_minmax(0,1.1fr)]">
        <section className="card min-w-0 self-start overflow-hidden xl:sticky xl:top-6" aria-label="Documents">
          <div className="border-b border-slate-100 p-5 sm:p-6">
            <div className="flex items-center justify-between gap-3"><div><p className="eyebrow">Queue</p><h2 className="mt-1 text-lg font-bold text-slate-900">Recent documents</h2></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-600">{pageCount} on this page</span></div>
            <label htmlFor="document-search" className="sr-only">Search documents</label>
            <input id="document-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search by filename" className="field mt-5 text-sm" />
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div><label className="block text-xs font-semibold" htmlFor="inbox-category">Category</label>
                <select id="inbox-category" className="field mt-1 !py-2 text-sm" value={category} onChange={event => selectCategory(event.target.value)}><option value="">All categories</option>{categories.data?.map(item => <option key={item.id} value={item.id}>{item.name}{item.active ? "" : " (archived)"}</option>)}</select></div>
              <div><label className="block text-xs font-semibold" htmlFor="inbox-type">Document type</label>
                <select id="inbox-type" className="field mt-1 !py-2 text-sm" value={typeFilter} onChange={event => selectType(event.target.value)}><option value="">All types</option>{typeChoices.map(type => <option key={type} value={type}>{documentTypeLabel(type)}</option>)}</select></div>
              <div><label className="block text-xs font-semibold" htmlFor="inbox-source">Source</label>
                <select id="inbox-source" className="field mt-1 !py-2 text-sm" value={sourceFilter} onChange={event => selectSource(isDocumentSource(event.target.value) ? event.target.value : "")}><option value="">All sources</option>{DOCUMENT_SOURCES.map(source => <option key={source} value={source}>{documentSourceLabel(source)}</option>)}</select></div>
            </div>
            <div role="group" aria-label="Filter documents by status" className="mt-3 flex flex-wrap gap-2">
              {statusFilters.map(option => <button key={option.value} type="button" aria-pressed={statusFilter === option.value} onClick={() => selectStatus(option.value)} className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${statusFilter === option.value ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>{option.label}</button>)}
            </div>
          </div>
          {documents.isError && <p role="alert" className="m-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-800">Could not load documents. <button type="button" className="font-bold underline" onClick={() => documents.refetch()}>Try again</button></p>}
          {documents.isLoading && <p role="status" className="p-6 text-sm text-slate-500">Loading documents…</p>}
          {showEmptyState && (filtersActive
            ? <div className="p-8 text-center"><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-2xl text-slate-500" aria-hidden="true">⌕</div><p className="mt-4 font-semibold text-slate-900">No documents match these filters.</p><p className="mt-1 text-sm text-slate-500">Try another status, type, source, category or search{offset > 0 ? ", or return to the first page" : ""}.</p><button type="button" className="secondary mt-4 text-xs" onClick={clearFilters}>Clear filters</button></div>
            : <div className="p-8 text-center"><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-blue-50 text-2xl text-blue-700" aria-hidden="true">▤</div><p className="mt-4 font-semibold text-slate-900">No documents yet.</p><p className="mt-1 text-sm text-slate-500">Upload your first document to start processing and review.</p></div>)}
          <div className={`max-h-[65vh] overflow-y-auto transition-opacity ${documents.isPlaceholderData ? "opacity-60" : ""}`} aria-label="Document list" aria-busy={documents.isPlaceholderData}>
            {documents.data?.map(item => <button key={item.id} type="button" aria-pressed={activeId === item.id} data-document-type={item.document_type} data-source={item.source} onClick={() => { setSelectedId(item.id); setUploadMessage(""); setRetryResult(null); }} className={`block w-full border-b border-slate-100 px-5 py-4 text-left transition-colors last:border-b-0 hover:bg-blue-50/70 ${activeId === item.id ? "border-l-4 border-l-blue-600 bg-blue-50/70 pl-4" : ""}`}>
              <span className="flex min-w-0 flex-wrap items-center justify-between gap-2"><span className="min-w-0 break-all text-sm font-bold text-slate-900">{item.filename}</span><StatusBadge status={item.status} /></span>
              <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500"><span>{formatDateTime(item.created_at)} · {fileSize(item.size_bytes)} · {documentTypeLabel(item.document_type)}</span><DocumentSourceBadge source={item.source} sourceRef={item.source_ref} /></span>
            </button>)}
          </div>
          <div className="flex items-center justify-between gap-3 border-t border-slate-100 p-4"><button className="secondary text-xs" type="button" disabled={offset === 0 || documents.isFetching} onClick={() => selectPage(offset - PAGE_SIZE)}>Previous</button><span className="text-xs text-slate-500">Page {offset / PAGE_SIZE + 1}</span><button className="secondary text-xs" type="button" disabled={!documents.data || documents.data.length < PAGE_SIZE || documents.isFetching} onClick={() => selectPage(offset + PAGE_SIZE)}>Next</button></div>
        </section>

        <section className="card min-w-0 self-start overflow-hidden" aria-label="Extraction result">
          <div className="border-b border-slate-100 p-5 sm:p-6"><p className="eyebrow">Document detail</p><h2 className="mt-1 text-lg font-bold text-slate-900">Extraction result</h2></div>
          <div className="p-5 sm:p-6">
            {!activeId && <p className="text-sm text-slate-500">Select a document to see its fields.</p>}
            {detail.isLoading && activeId && <p role="status" className="text-sm text-slate-500">Loading result…</p>}
            {detail.isError && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">Could not load this document. <button type="button" className="font-bold underline" onClick={() => detail.refetch()}>Try again</button></p>}
            {detail.data && !detail.isError && <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="break-all text-lg font-bold text-slate-900">{detail.data.filename}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500"><span>Status: <span className="capitalize">{documentStatusLabel(detail.data.status)}</span> · <span data-testid="detail-document-type">{documentTypeLabel(detail.data.document_type)}</span> · Workflow v{detail.data.workflow_config_version}{detail.data.provider && ` · Provider: ${detail.data.provider}`}</span><DocumentSourceBadge source={detail.data.source} sourceRef={detail.data.source_ref} /></p>
                </div>
                <StatusBadge status={detail.data.status} />
              </div>
              {isDocumentInProgress(detail.data.status) && <p role="status" className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">Extraction is running. This result updates automatically.</p>}
              {detail.data.failure_reason && <p role="alert" className="rounded-xl border border-rose-100 bg-rose-50 p-4 text-sm text-rose-800">{detail.data.failure_reason}</p>}
              <NearDuplicateBanner duplicates={detail.data.near_duplicates} onOpen={id => { setSelectedId(id); setRetryResult(null); }} />
              {detail.data.status === "failed" && canUpload && <button type="button" className="primary" disabled={retryingId !== null || exhaustedRetryIds.has(detail.data.id)} onClick={retryFailedDocument}>{retryingId === detail.data.id ? "Queueing retry…" : exhaustedRetryIds.has(detail.data.id) ? "Retry limit reached" : "Retry extraction"}</button>}
              {retryResult?.id === detail.data.id && <p role={retryResult.error ? "alert" : "status"} className={`rounded-xl p-4 text-sm ${retryResult.error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-900"}`}>{retryResult.message}</p>}
              {detail.data.status === "needs_review" && <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><strong>Evidence ready.</strong> The fields below were extracted and checked against the PDF. Open the full document, verify the values, and record a review decision below.</p>}
              {detail.data.context_text && <section aria-labelledby="message-context-heading" data-testid="message-context" className="rounded-xl border border-violet-200 bg-violet-50/60 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2"><h3 id="message-context-heading" className="text-xs font-bold uppercase tracking-[.12em] text-violet-900">Message context</h3>{detail.data.source_ref && <span className="break-all text-xs text-violet-800">{detail.data.source_ref}</span>}</div>
                <p className="mt-1 text-xs text-violet-800">The body of the email this document arrived with, kept for the reviewer.</p>
                <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-3 font-sans text-sm leading-6 text-slate-800">{detail.data.context_text}</pre>
              </section>}
              {detail.data.fields.length > 0 && (() => {
                const fieldSummary = summarizeFieldStatuses(detail.data.fields);
                return <div role="group" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4" aria-label="Confidence summary">
                  <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
                    <span className={`rounded-full border px-2.5 py-1 ${fieldSummary.flagged > 0 ? "border-amber-300 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-600"}`}>{fieldSummary.flagged} flagged</span>
                    <span className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-sky-800">{fieldSummary.auto} auto</span>
                    <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-violet-800">{fieldSummary.corrected} corrected</span>
                    {fieldSummary.accepted > 0 && <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-emerald-800">{fieldSummary.accepted} accepted</span>}
                  </div>
                  <Link href={`/review/${encodeURIComponent(detail.data.id)}`} className="secondary text-xs">Open in review →</Link>
                </div>;
              })()}
              {detail.data.fields.length > 0 && <div><h3 className="mb-3 text-xs font-bold uppercase tracking-[.12em] text-slate-500">Extracted fields and evidence</h3><dl className="grid gap-3 sm:grid-cols-2">
                {detail.data.fields.map(field => <div key={field.name} className="min-w-0 rounded-xl border border-slate-200 bg-slate-50/70 p-4" data-field-name={field.name}><div className="flex flex-wrap items-start justify-between gap-2"><dt className="text-xs font-bold uppercase tracking-wide text-slate-500">{field.name.replaceAll("_", " ")}</dt><span className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-500"><span className="tabular-nums" title={`Confidence ${percent(field.confidence)}%, threshold ${percent(field.threshold)}%`}>{percent(field.confidence)}%</span><FieldStatusChip status={field.status} /></span></div><dd className="mt-2 break-words text-base font-bold text-slate-900">{field.current_value}</dd>{field.status === "corrected" && <dd className="mt-1 text-xs text-slate-500">Extracted <s className="text-slate-400">{field.value}</s></dd>}{field.reasons.length > 0 && field.status === "needs_review" && <dd className="mt-1 text-xs text-amber-900">{field.reasons.join(" · ")}</dd>}<dd className="mt-3 border-t border-slate-200 pt-3 text-xs leading-5 text-slate-600"><span className="font-bold text-blue-700">Evidence · page {field.page_number}</span><br />“{field.evidence}”</dd></div>)}
              </dl></div>}
              <InvoiceWorkspace key={detail.data.id} documentId={detail.data.id} status={detail.data.status} orgId={session.data.org_id} userId={session.data.user_id} />
            </div>}
          </div>
        </section>
      </div>
    </div>
  </AppShell>;
}
