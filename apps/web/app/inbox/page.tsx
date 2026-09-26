"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";

export default function InboxPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: async () => {
      const result = await api.GET("/v1/documents");
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load documents");
      return result.data;
    },
    refetchInterval: 2000,
  });
  const activeId = selectedId ?? documents.data?.[0]?.id;
  const detail = useQuery({
    queryKey: ["document", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => {
      if (!activeId) throw new Error("No document selected");
      const result = await api.GET("/v1/documents/{document_id}", {
        params: { path: { document_id: activeId } },
      });
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load document");
      return result.data;
    },
    refetchInterval: 2000,
  });
  useEffect(() => {
    if (documents.error?.message === "Unauthorized" || detail.error?.message === "Unauthorized") {
      router.replace("/login");
    }
  }, [documents.error, detail.error, router]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
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
      if (result.error || !result.data) {
        setError("Upload failed. Use a PDF smaller than 10 MB and try again.");
        return;
      }
      setSelectedId(result.data.id);
      setFile(null);
      const input = document.getElementById("invoice-file") as HTMLInputElement | null;
      if (input) input.value = "";
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
    } catch {
      setError("Could not reach the API. Try again shortly.");
    } finally {
      setUploading(false);
    }
  }

  return <main className="min-h-screen p-5 md:p-10">
    <div className="mx-auto max-w-6xl">
      <Link href="/dashboard" className="text-sm text-blue-700 hover:underline">← Dashboard</Link>
      <div className="mt-6 mb-8">
        <p className="text-sm font-semibold uppercase tracking-wider text-blue-700">Document operations</p>
        <h1 className="mt-2 text-3xl font-bold">Inbox</h1>
        <p className="mt-2 text-slate-500">Upload a text-layer PDF invoice. The configured provider extracts fields and evidence for review.</p>
      </div>
      <form onSubmit={upload} className="card mb-7 flex flex-col gap-4 p-5 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="invoice-file" className="mb-2 block text-sm font-semibold">Invoice PDF</label>
          <input id="invoice-file" type="file" accept="application/pdf,.pdf" onChange={event => setFile(event.target.files?.[0] ?? null)} className="field" />
        </div>
        <button className="primary" disabled={!file || uploading} type="submit">{uploading ? "Uploading…" : "Upload invoice"}</button>
      </form>
      {error && <p role="alert" className="mb-5 text-red-700">{error}</p>}
      {documents.isError && <p role="alert">Could not load documents. <button className="text-blue-700 underline" onClick={() => documents.refetch()}>Try again</button></p>}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <section className="card p-5" aria-label="Documents">
          <h2 className="mb-4 text-lg font-semibold">Recent documents</h2>
          {documents.isLoading && <p role="status">Loading documents…</p>}
          {documents.data?.length === 0 && <p className="text-slate-500">No documents yet. Upload the sample invoice from <code>examples/northwind-invoice.pdf</code> to try the workflow.</p>}
          <div className="space-y-2">
            {documents.data?.map(item => <button key={item.id} type="button" onClick={() => setSelectedId(item.id)} className={`w-full rounded-lg border p-3 text-left hover:bg-blue-50 ${activeId === item.id ? "border-blue-500" : "border-slate-200"}`}>
              <span className="block font-semibold break-all">{item.filename}</span>
              <span className="mt-1 block text-sm text-slate-500">{item.status.replaceAll("_", " ")} · {new Date(item.created_at).toLocaleString()}</span>
            </button>)}
          </div>
        </section>
        <section className="card p-5" aria-label="Extraction result">
          <h2 className="mb-4 text-lg font-semibold">Extraction result</h2>
          {!activeId && <p className="text-slate-500">Select a document to see its fields.</p>}
          {detail.isLoading && activeId && <p role="status">Loading result…</p>}
          {detail.isError && <p role="alert">Could not load this document.</p>}
          {detail.data && <div>
            <p className="font-semibold break-all">{detail.data.filename}</p>
            <p className="mt-1 text-sm text-slate-500">Status: {detail.data.status.replaceAll("_", " ")} · Workflow config v{detail.data.workflow_config_version}{detail.data.provider && ` · Provider: ${detail.data.provider}`}</p>
            {detail.data.failure_reason && <p role="alert" className="mt-4 text-red-700">{detail.data.failure_reason}</p>}
            {detail.data.status === "needs_review" && <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Fields are extracted. Human review and approval are coming in the next phase.</p>}
            <dl className="mt-5 space-y-4">
              {detail.data.fields.map(field => <div key={field.name} className="border-b border-slate-200 pb-3">
                <dt className="text-sm font-semibold capitalize">{field.name.replaceAll("_", " ")}</dt>
                <dd className="mt-1 text-lg">{field.value}</dd>
                <dd className="mt-1 text-xs text-slate-500">Evidence: “{field.evidence}” · page {field.page_number}</dd>
              </div>)}
            </dl>
          </div>}
        </section>
      </div>
    </div>
  </main>;
}
