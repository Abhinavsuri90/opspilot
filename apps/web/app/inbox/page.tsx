"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { documentStatusLabel, isDocumentInProgress } from "@/lib/document-status";
import { classifyRetryFailure } from "@/lib/retry";
import { validatePdfSelection } from "@/lib/upload";

export default function InboxPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [uploadMessage, setUploadMessage] = useState("");
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [retryResult, setRetryResult] = useState<{ id: string; error: boolean; message: string } | null>(null);
  const [exhaustedRetryIds, setExhaustedRetryIds] = useState<Set<string>>(() => new Set());

  const session = useQuery({
    queryKey: ["session"],
    retry: false,
    queryFn: async () => {
      const result = await api.GET("/v1/auth/me");
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load your session");
      return result.data;
    },
  });

  const documents = useQuery({
    queryKey: ["documents", session.data?.org_id],
    enabled: Boolean(session.data) && !session.isFetching && !session.isError,
    queryFn: async () => {
      const result = await api.GET("/v1/documents");
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load documents");
      return result.data;
    },
    refetchInterval: query => query.state.data?.some(item => isDocumentInProgress(item.status)) ? 2000 : 15000,
  });
  const activeId = selectedId ?? documents.data?.[0]?.id;
  const detail = useQuery({
    queryKey: ["document", activeId, session.data?.org_id],
    enabled: Boolean(activeId) && Boolean(session.data) && !session.isFetching && !session.isError,
    queryFn: async () => {
      if (!activeId) throw new Error("No document selected");
      const result = await api.GET("/v1/documents/{document_id}", {
        params: { path: { document_id: activeId } },
      });
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load document");
      return result.data;
    },
    refetchInterval: query => !query.state.data || isDocumentInProgress(query.state.data.status) ? 2000 : false,
  });
  useEffect(() => {
    if (session.error?.message === "Unauthorized" || documents.error?.message === "Unauthorized" || detail.error?.message === "Unauthorized") {
      queryClient.clear();
      router.replace("/login");
    }
  }, [session.error, documents.error, detail.error, queryClient, router]);

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
  if (session.isFetching || !session.data) {
    return <main className="p-8 text-slate-500" role="status">Checking your session…</main>;
  }
  const canUpload = session.data.role === "admin" || session.data.role === "reviewer";

  return <main className="min-h-screen p-5 md:p-10">
    <div className="mx-auto max-w-6xl">
      <Link href="/dashboard" className="text-sm text-blue-700 hover:underline">← Dashboard</Link>
      <div className="mt-6 mb-8">
        <p className="text-sm font-semibold uppercase tracking-wider text-blue-700">Document operations</p>
        <h1 className="mt-2 text-3xl font-bold">Inbox</h1>
        <p className="mt-2 text-slate-600 dark:text-slate-300">Upload a text-layer PDF invoice to extract fields with evidence. Scanned PDFs need OCR, which is not yet available.</p>
      </div>
      {canUpload ? <form onSubmit={upload} className="card mb-7 flex flex-col gap-4 p-5 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="invoice-file" className="mb-2 block text-sm font-semibold">Invoice PDF</label>
          <input ref={fileInput} id="invoice-file" type="file" accept="application/pdf,.pdf" disabled={uploading} onChange={event => { setFile(event.target.files?.[0] ?? null); setError(""); }} className="field" />
          <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">PDF only, up to 10 MB. <a href="/sample-invoice.pdf" download className="text-blue-700 underline dark:text-blue-300">Download sample invoice</a></p>
        </div>
        <button className="primary" disabled={!file || uploading} type="submit">{uploading ? "Uploading…" : "Upload invoice"}</button>
      </form> : <p className="card mb-7 p-5 text-sm text-slate-600 dark:text-slate-300">Your workspace role can view invoices but cannot upload them.</p>}
      {error && <p role="alert" className="mb-5 rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
      {uploadMessage && <p role="status" className="mb-5 rounded-lg bg-green-50 p-3 text-green-900">{uploadMessage}</p>}
      {documents.isError && <p role="alert">Could not load documents. <button type="button" className="text-blue-700 underline dark:text-blue-300" onClick={() => documents.refetch()}>Try again</button></p>}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <section className="card p-5" aria-label="Documents">
          <h2 className="mb-4 text-lg font-semibold">Recent documents</h2>
          {documents.isLoading && <p role="status">Loading documents…</p>}
          {documents.data?.length === 0 && <p className="text-slate-600 dark:text-slate-300">No documents yet. Download the sample invoice above, then upload it to try the workflow.</p>}
          <div className="max-h-[65vh] space-y-2 overflow-y-auto pr-1" aria-label="Document list">
            {documents.data?.map(item => <button key={item.id} type="button" aria-pressed={activeId === item.id} onClick={() => { setSelectedId(item.id); setUploadMessage(""); setRetryResult(null); }} className={`w-full rounded-lg border p-3 text-left hover:bg-blue-50 dark:hover:bg-slate-700 ${activeId === item.id ? "border-blue-500 dark:border-blue-400" : "border-slate-200 dark:border-slate-700"}`}>
              <span className="block font-semibold break-all">{item.filename}</span>
              <span className="mt-1 block text-sm text-slate-600 dark:text-slate-300">{documentStatusLabel(item.status)} · {new Date(item.created_at).toLocaleString()}</span>
            </button>)}
          </div>
        </section>
        <section className="card self-start p-5" aria-label="Extraction result">
          <h2 className="mb-4 text-lg font-semibold">Extraction result</h2>
          {!activeId && <p className="text-slate-600 dark:text-slate-300">Select a document to see its fields.</p>}
          {detail.isLoading && activeId && <p role="status">Loading result…</p>}
          {detail.isError && <p role="alert">Could not load this document. <button type="button" className="text-blue-700 underline dark:text-blue-300" onClick={() => detail.refetch()}>Try again</button></p>}
          {detail.data && <div>
            <p className="font-semibold break-all">{detail.data.filename}</p>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Status: <span className="capitalize">{documentStatusLabel(detail.data.status)}</span> · Workflow config v{detail.data.workflow_config_version}{detail.data.provider && ` · Provider: ${detail.data.provider}`}</p>
            {isDocumentInProgress(detail.data.status) && <p role="status" className="mt-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-900">Extraction is running. This page updates automatically.</p>}
            {detail.data.failure_reason && <p role="alert" className="mt-4 text-red-700">{detail.data.failure_reason}</p>}
            {detail.data.status === "failed" && (session.data?.role === "admin" || session.data?.role === "reviewer") && <button type="button" className="primary mt-4" disabled={retryingId !== null || exhaustedRetryIds.has(detail.data.id)} onClick={retryFailedDocument}>{retryingId === detail.data.id ? "Queueing retry…" : exhaustedRetryIds.has(detail.data.id) ? "Retry limit reached" : "Retry extraction"}</button>}
            {retryResult?.id === detail.data.id && <p role={retryResult.error ? "alert" : "status"} className={`mt-4 rounded-lg p-3 text-sm ${retryResult.error ? "bg-red-50 text-red-800" : "bg-green-50 text-green-900"}`}>{retryResult.message}</p>}
            {detail.data.status === "needs_review" && <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Fields are extracted. Human review and approval are coming in the next phase.</p>}
            <dl className="mt-5 space-y-4">
              {detail.data.fields.map(field => <div key={field.name} className="border-b border-slate-200 pb-3">
                <dt className="text-sm font-semibold capitalize">{field.name.replaceAll("_", " ")}</dt>
                <dd className="mt-1 break-words text-lg">{field.value}</dd>
                <dd className="mt-1 break-words text-xs text-slate-600 dark:text-slate-300">Evidence: “{field.evidence}” · page {field.page_number}</dd>
              </div>)}
            </dl>
          </div>}
        </section>
      </div>
    </div>
  </main>;
}
