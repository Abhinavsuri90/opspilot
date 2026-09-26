"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { InvoiceWorkspace } from "@/components/InvoiceWorkspace";
import { api } from "@/lib/api";
import { documentStatusLabel, isDocumentInProgress } from "@/lib/document-status";
import { classifyRetryFailure } from "@/lib/retry";
import { validatePdfSelection } from "@/lib/upload";

type StatusFilter = "all" | "in_progress" | "needs_review" | "failed" | "approved" | "rejected";

const statusFilters: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "in_progress", label: "In progress" },
  { value: "needs_review", label: "Needs review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "failed", label: "Failed" },
];

function StatusBadge({ status }: { status: string }) {
  const tone = status === "needs_review"
    ? "border-amber-200 bg-amber-50 text-amber-800"
    : status === "failed"
      ? "border-rose-200 bg-rose-50 text-rose-700"
      : "border-blue-200 bg-blue-50 text-blue-700";
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold capitalize ${tone}`}>
    <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />{documentStatusLabel(status)}
  </span>;
}

export default function InboxPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const deepLinkApplied = useRef(false);
  const [file, setFile] = useState<File | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [uploadMessage, setUploadMessage] = useState("");
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [retryResult, setRetryResult] = useState<{ id: string; error: boolean; message: string } | null>(null);
  const [exhaustedRetryIds, setExhaustedRetryIds] = useState<Set<string>>(() => new Set());
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [offset, setOffset] = useState(0);
  const [serverSearch, setServerSearch] = useState("");
  useEffect(() => { const timer = setTimeout(() => { setServerSearch(search.trim()); setOffset(0); }, 300); return () => clearTimeout(timer); }, [search]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [dragging, setDragging] = useState(false);

  const session = useQuery({
    queryKey: ["session"],
    refetchInterval: 15000,
    retry: false,
    queryFn: async () => {
      const result = await api.GET("/v1/auth/me");
      if (result.response.status === 401 || result.response.status === 403) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load your session");
      return result.data;
    },
  });

  const categories = useQuery({ queryKey: ["categories", session.data?.org_id, session.data?.user_id], enabled: Boolean(session.data), queryFn: async () => { const result = await api.GET("/v1/categories"); if (!result.data || result.error) throw new Error("Could not load categories"); return result.data; } });
  const documents = useQuery({
    queryKey: ["documents", session.data?.user_id, session.data?.org_id, offset, category, serverSearch, statusFilter],
    enabled: Boolean(session.data) && !session.isError,
    queryFn: async () => {
      const result = await api.GET("/v1/documents", { params: { query: { offset, limit: 50, category_id: category || undefined, q: serverSearch || undefined, status: statusFilter !== "all" ? statusFilter : undefined } } });
      if (result.response.status === 401 || result.response.status === 403) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load documents");
      return result.data;
    },
    refetchInterval: query => query.state.data?.some(item => isDocumentInProgress(item.status)) ? 2000 : 15000,
  });
  const activeId = selectedId ?? documents.data?.[0]?.id;
  const detail = useQuery({
    queryKey: ["document", activeId, session.data?.org_id, session.data?.user_id],
    enabled: Boolean(activeId) && Boolean(session.data) && !session.isError,
    queryFn: async () => {
      if (!activeId) throw new Error("No document selected");
      const result = await api.GET("/v1/documents/{document_id}", {
        params: { path: { document_id: activeId } },
      });
      if (result.response.status === 401 || result.response.status === 403) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load document");
      return result.data;
    },
    refetchInterval: query => !query.state.data || isDocumentInProgress(query.state.data.status) ? 2000 : 15000,
  });
  useEffect(() => {
    if (session.error?.message === "Unauthorized" || documents.error?.message === "Unauthorized" || detail.error?.message === "Unauthorized") {
      queryClient.clear();
      router.replace("/login");
    }
  }, [session.error, documents.error, detail.error, queryClient, router]);

  useEffect(() => {
    if (deepLinkApplied.current) return;
    const requestedId = new URLSearchParams(window.location.search).get("document");
    if (requestedId && /^[0-9a-f-]{36}$/i.test(requestedId)) {
      setSelectedId(requestedId);
      deepLinkApplied.current = true;
    }
  }, [documents.data]);

  const visibleDocuments = useMemo(() => (documents.data ?? []).filter(item => {
    const matchesSearch = item.filename.toLowerCase().includes(search.trim().toLowerCase());
    const matchesStatus = statusFilter === "all"
      || (statusFilter === "in_progress" && isDocumentInProgress(item.status))
      || item.status === statusFilter;
    return matchesSearch && matchesStatus;
  }), [documents.data, search, statusFilter]);

  const counts = useMemo(() => ({
    total: documents.data?.length ?? 0,
    inProgress: documents.data?.filter(item => isDocumentInProgress(item.status)).length ?? 0,
    needsReview: documents.data?.filter(item => item.status === "needs_review").length ?? 0,
    failed: documents.data?.filter(item => item.status === "failed").length ?? 0,
  }), [documents.data]);

  function acceptDroppedFile(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (!event.dataTransfer.files.length) return;
    const selected = event.dataTransfer.files[0];
    setFile(selected);
    setError("");
    if (fileInput.current) fileInput.current.value = "";
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setUploadMessage("");
    const validationError = validatePdfSelection(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    setUploading(true);
    setError("");
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
        const status = result.response.status;
        setError(status === 403
          ? "Your account cannot upload invoices."
          : status === 409
            ? "This workspace cannot accept another invoice. Check its workflow configuration or document limit."
            : status === 400 || status === 413
              ? "The PDF could not be accepted. Use a text-layer PDF smaller than 10 MB."
              : "The upload service is temporarily unavailable. Please try again.");
        return;
      }
      setSelectedId(result.data.id);
      setUploadMessage(result.data.duplicate
        ? "This invoice was already uploaded. Its existing result is open below."
        : "Invoice uploaded. Extraction is in progress; the result will appear below.");
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
    } catch {
      setError("Could not reach the API. Try again shortly.");
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
      ]);
    } catch {
      setRetryResult({ id, error: true, message: "Could not reach the API. Please try again." });
    } finally {
      setRetryingId(null);
    }
  }

  const unauthorized = [session.error, documents.error, detail.error]
    .some(queryError => queryError?.message === "Unauthorized");
  if (unauthorized) {
    return <main className="p-8 text-slate-500" role="status">Checking your session…</main>;
  }
  if (session.isError) {
    return <main className="p-8">
      <p role="alert">Could not load your workspace.</p>
      <button type="button" onClick={() => session.refetch()} className="primary mt-4">Try again</button>
    </main>;
  }
  if (session.isPending || !session.data) {
    return <main className="p-8 text-slate-500" role="status">Checking your session…</main>;
  }
  const canUpload = session.data.role === "admin" || session.data.role === "reviewer" || session.data.role === "member";

  return <AppShell session={session.data} active="inbox">
    <div className="mx-auto max-w-[1440px] space-y-6 pb-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Document operations / Inbox</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 md:text-4xl">Invoice inbox</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">Upload a text-layer PDF, follow extraction, and inspect every field against its source text.</p>
        </div>
        <div className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600">{session.data.org_name} workspace</div>
      </header>

      <div className="grid gap-3 sm:grid-cols-3" aria-label="Recent document summary">
        <div className="card flex items-center gap-4 p-4"><span className="grid h-11 w-11 place-items-center rounded-xl bg-blue-50 text-xl text-blue-700" aria-hidden="true">↗</span><div><p className="text-xs font-semibold text-slate-500">In progress</p><p className="text-2xl font-bold text-slate-900">{counts.inProgress}</p></div></div>
        <div className="card flex items-center gap-4 p-4"><span className="grid h-11 w-11 place-items-center rounded-xl bg-amber-50 text-xl text-amber-700" aria-hidden="true">◎</span><div><p className="text-xs font-semibold text-slate-500">Needs review</p><p className="text-2xl font-bold text-slate-900">{counts.needsReview}</p></div></div>
        <div className="card flex items-center gap-4 p-4"><span className="grid h-11 w-11 place-items-center rounded-xl bg-rose-50 text-xl text-rose-700" aria-hidden="true">!</span><div><p className="text-xs font-semibold text-slate-500">Failed</p><p className="text-2xl font-bold text-slate-900">{counts.failed}</p></div></div>
      </div>
      <p className="-mt-4 text-xs text-slate-500">Counts cover the {counts.total} documents on this page. Workspace-wide totals are in Insights.</p>

      {canUpload ? <form onSubmit={upload} className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-6">
          <div><h2 className="text-base font-bold text-slate-900">Add an invoice</h2><p className="mt-0.5 text-xs text-slate-500">PDF only · maximum 10 MB · text layer required</p></div>
          <a href="/sample-invoice.pdf" download className="secondary text-sm">Download sample invoice</a>
        </div>
        <div className="grid gap-5 p-5 sm:p-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={acceptDroppedFile} className={`rounded-2xl border-2 border-dashed p-4 transition-colors ${dragging ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-slate-50/60"}`}>
            <label htmlFor="invoice-file" className="mb-2 block text-sm font-semibold text-slate-800">Invoice PDF</label>
            <input ref={fileInput} id="invoice-file" type="file" accept="application/pdf,.pdf" disabled={uploading} onChange={event => { setFile(event.target.files?.[0] ?? null); setError(""); }} className="block w-full cursor-pointer text-sm text-slate-600 file:mr-4 file:rounded-lg file:border-0 file:bg-white file:px-3 file:py-2 file:font-semibold file:text-blue-700 hover:file:bg-blue-50" />
            <p className="mt-2 text-xs text-slate-500">{file ? `Selected: ${file.name}` : "Choose a file or drag it here. Scanned PDFs need OCR and cannot be extracted yet."}</p>
          </div>
          <button className="primary w-full lg:w-auto" disabled={!file || uploading} type="submit">{uploading ? "Uploading…" : "Upload invoice"}<span aria-hidden="true">→</span></button>
        </div>
      </form> : <p className="card p-5 text-sm text-slate-600">Your workspace role can view invoices but cannot upload them.</p>}

      {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</p>}
      {uploadMessage && <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{uploadMessage}</p>}

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(320px,.9fr)_minmax(0,1.1fr)]">
        <section className="card min-w-0 self-start overflow-hidden xl:sticky xl:top-6" aria-label="Documents">
          <div className="border-b border-slate-100 p-5 sm:p-6">
            <div className="flex items-center justify-between gap-3"><div><p className="eyebrow">Queue</p><h2 className="mt-1 text-lg font-bold text-slate-900">Recent documents</h2></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-600">{counts.total} items</span></div>
            <label htmlFor="document-search" className="sr-only">Search documents</label>
            <input id="document-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search by filename" className="field mt-5 text-sm" />
            <label className="mt-3 block text-xs font-semibold" htmlFor="inbox-category">Filter by category</label>
            <select id="inbox-category" className="field mt-1 text-sm" value={category} onChange={event => { setCategory(event.target.value); setOffset(0); }}><option value="">All categories</option>{categories.data?.map(item => <option key={item.id} value={item.id}>{item.name}{item.active ? "" : " (archived)"}</option>)}</select>
            <div role="group" aria-label="Filter documents by status" className="mt-3 flex flex-wrap gap-2">
              {statusFilters.map(option => <button key={option.value} type="button" aria-pressed={statusFilter === option.value} onClick={() => { setStatusFilter(option.value); setOffset(0); }} className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${statusFilter === option.value ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>{option.label}</button>)}
            </div>
          </div>
          {documents.isError && <p role="alert" className="m-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-800">Could not load documents. <button type="button" className="font-bold underline" onClick={() => documents.refetch()}>Try again</button></p>}
          {documents.isLoading && <p role="status" className="p-6 text-sm text-slate-500">Loading documents…</p>}
          {documents.data?.length === 0 && <div className="p-8 text-center"><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-blue-50 text-2xl text-blue-700" aria-hidden="true">▤</div><p className="mt-4 font-semibold text-slate-900">No documents yet.</p><p className="mt-1 text-sm text-slate-500">Upload your first invoice to start processing and review.</p></div>}
          {Boolean(documents.data?.length) && visibleDocuments.length === 0 && <p className="p-6 text-sm text-slate-500">No documents match this search or status. Clear the filter to see your queue.</p>}
          <div className="max-h-[65vh] overflow-y-auto" aria-label="Document list">
            {visibleDocuments.map(item => <button key={item.id} type="button" aria-pressed={activeId === item.id} onClick={() => { setSelectedId(item.id); setUploadMessage(""); setRetryResult(null); }} className={`block w-full border-b border-slate-100 px-5 py-4 text-left transition-colors last:border-b-0 hover:bg-blue-50/70 ${activeId === item.id ? "border-l-4 border-l-blue-600 bg-blue-50/70 pl-4" : ""}`}>
              <span className="flex min-w-0 flex-wrap items-center justify-between gap-2"><span className="min-w-0 break-all text-sm font-bold text-slate-900">{item.filename}</span><StatusBadge status={item.status} /></span>
              <span className="mt-2 block text-xs text-slate-500">{new Date(item.created_at).toLocaleString()} · {Math.max(1, Math.ceil(item.size_bytes / 1024))} KB</span>
            </button>)}
          </div>
          <div className="flex items-center justify-between gap-3 border-t border-slate-100 p-4"><button className="secondary text-xs" type="button" disabled={offset === 0 || documents.isFetching} onClick={() => { setOffset(value => Math.max(0, value - 50)); setSelectedId(null); }}>Previous</button><span className="text-xs text-slate-500">Page {offset / 50 + 1}</span><button className="secondary text-xs" type="button" disabled={!documents.data || documents.data.length < 50 || documents.isFetching} onClick={() => { setOffset(value => value + 50); setSelectedId(null); }}>Next</button></div>
        </section>

        <section className="card min-w-0 self-start overflow-hidden" aria-label="Extraction result">
          <div className="border-b border-slate-100 p-5 sm:p-6"><p className="eyebrow">Document detail</p><h2 className="mt-1 text-lg font-bold text-slate-900">Extraction result</h2></div>
          <div className="p-5 sm:p-6">
            {!activeId && <p className="text-sm text-slate-500">Select a document to see its fields.</p>}
            {detail.isLoading && activeId && <p role="status" className="text-sm text-slate-500">Loading result…</p>}
            {detail.isError && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">Could not load this document. <button type="button" className="font-bold underline" onClick={() => detail.refetch()}>Try again</button></p>}
            {detail.data && !detail.isError && <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><p className="break-all text-lg font-bold text-slate-900">{detail.data.filename}</p><p className="mt-1 text-xs text-slate-500">Status: <span className="capitalize">{documentStatusLabel(detail.data.status)}</span> · Workflow v{detail.data.workflow_config_version}{detail.data.provider && ` · Provider: ${detail.data.provider}`}</p></div><StatusBadge status={detail.data.status} /></div>
              {isDocumentInProgress(detail.data.status) && <p role="status" className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">Extraction is running. This result updates automatically.</p>}
              {detail.data.failure_reason && <p role="alert" className="rounded-xl border border-rose-100 bg-rose-50 p-4 text-sm text-rose-800">{detail.data.failure_reason}</p>}
              {detail.data.status === "failed" && canUpload && <button type="button" className="primary" disabled={retryingId !== null || exhaustedRetryIds.has(detail.data.id)} onClick={retryFailedDocument}>{retryingId === detail.data.id ? "Queueing retry…" : exhaustedRetryIds.has(detail.data.id) ? "Retry limit reached" : "Retry extraction"}</button>}
              {retryResult?.id === detail.data.id && <p role={retryResult.error ? "alert" : "status"} className={`rounded-xl p-4 text-sm ${retryResult.error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-900"}`}>{retryResult.message}</p>}
              {detail.data.status === "needs_review" && <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><strong>Evidence ready.</strong> The fields below were extracted and checked against the PDF. Open the full document, verify the amount, and record a review decision below.</p>}
              {detail.data.fields.length > 0 && <div><h3 className="mb-3 text-xs font-bold uppercase tracking-[.12em] text-slate-500">Extracted fields and evidence</h3><dl className="grid gap-3 sm:grid-cols-2">
                {detail.data.fields.map(field => <div key={field.name} className="min-w-0 rounded-xl border border-slate-200 bg-slate-50/70 p-4"><dt className="text-xs font-bold uppercase tracking-wide text-slate-500">{field.name.replaceAll("_", " ")}</dt><dd className="mt-2 break-words text-base font-bold text-slate-900">{field.value}</dd><dd className="mt-3 border-t border-slate-200 pt-3 text-xs leading-5 text-slate-600"><span className="font-bold text-blue-700">Evidence · page {field.page_number}</span><br />“{field.evidence}”</dd></div>)}
              </dl></div>}
              <InvoiceWorkspace key={detail.data.id} documentId={detail.data.id} status={detail.data.status} orgId={session.data.org_id} userId={session.data.user_id} />
            </div>}
          </div>
        </section>
      </div>
    </div>
  </AppShell>;
}
