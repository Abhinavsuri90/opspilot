"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { InvoiceQuestions } from "@/components/InvoiceQuestions";
import { PdfViewer } from "@/components/PdfViewer";
import { AccessForm } from "@/components/workspace/AccessForm";
import { Discussion } from "@/components/workspace/Discussion";
import { MetadataForm } from "@/components/workspace/MetadataForm";
import { ReviewDecision } from "@/components/workspace/ReviewDecision";
import { saveMessage, sendSave, type SaveInput } from "@/components/workspace/save";
import { metadataSnapshot, sharingSnapshot, type MetadataDraft, type SharingDraft } from "@/components/workspace/types";
import { formatDateTime } from "@/lib/format";
import { documentFileUrl } from "@/lib/urls";

export function InvoiceWorkspace({ documentId, status, orgId, userId }: { documentId: string; status: string; orgId: string; userId: string }) {
  const client = useQueryClient();
  const [tab, setTab] = useState<"review" | "pdf" | "access" | "questions">("review");
  const [notice, setNotice] = useState("");
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  // A draft keeps the server version from the first edit. Polling can refresh
  // the saved record without erasing edits or silently rebasing a stale write.
  const [metadataDraft, setMetadataDraft] = useState<MetadataDraft | null>(null);
  const [sharingDraft, setSharingDraft] = useState<SharingDraft | null>(null);
  const workspace = useQuery({ queryKey: ["invoice-workspace", documentId, orgId, userId], queryFn: async () => {
    const result = await api.GET("/v1/documents/{document_id}/workspace", { params: { path: { document_id: documentId } } });
    if (!result.data || result.error) throw new Error("Could not load invoice collaboration. Your access may have changed.");
    return result.data;
  }, refetchInterval: 15000 });
  const categories = useQuery({ queryKey: ["categories", orgId, userId], queryFn: async () => { const result = await api.GET("/v1/categories"); if (!result.data || result.error) throw new Error("Could not load categories"); return result.data; } });
  const collaborators = useQuery({ queryKey: ["collaborators", orgId, userId], queryFn: async () => { const result = await api.GET("/v1/organization/collaborators"); if (!result.data || result.error) throw new Error("Could not load teammates"); return result.data; } });
  const save = useMutation({
    mutationFn: async (input: SaveInput) => {
      const current = workspace.data;
      if (!current) throw new Error("Load the invoice before editing it.");
      const result = await sendSave(documentId, current, input);
      if (!result.data || result.error) throw new Error(saveMessage(result.error, result.response.status));
      return result.data;
    },
    onSuccess: async (saved, input) => {
      client.setQueryData(["invoice-workspace", documentId, orgId, userId], saved);
      if (input.action === "comments") setComment("");
      if (input.action === "review") setReason("");
      if (input.action === "metadata") setMetadataDraft(null);
      if (input.action === "sharing") setSharingDraft(null);
      setNotice("Changes saved.");
      await Promise.all(["document", "documents", "review-queue", "timeline", "workspace-summary"].map(key => client.invalidateQueries({ queryKey: [key] })));
    },
    onError: () => { setNotice(""); },
  });
  function submit(event: FormEvent<HTMLFormElement>, action: "metadata" | "sharing") {
    event.preventDefault();
    if (!workspace.data || save.isPending) return;
    if (action === "metadata") save.mutate({ action, metadata: metadataDraft ?? metadataSnapshot(workspace.data) });
    else save.mutate({ action, sharing: sharingDraft ?? sharingSnapshot(workspace.data) });
  }
  async function copyLink() { try { await navigator.clipboard.writeText(`${window.location.origin}/inbox?document=${documentId}`); setNotice("Invoice link copied. The recipient must sign in and have access."); } catch { setNotice("Copy the invoice link from the Open PDF or invoice address."); } }
  const data = workspace.isError ? undefined : workspace.data;
  const metadata = metadataDraft ?? (data ? metadataSnapshot(data) : null);
  const sharing = sharingDraft ?? (data ? sharingSnapshot(data) : null);
  function editMetadata(values: Partial<MetadataDraft>) { if (metadata) setMetadataDraft({ ...metadata, ...values }); }
  function editSharing(values: Partial<SharingDraft>) { if (sharing) setSharingDraft({ ...sharing, ...values }); }
  return <div className="space-y-4 border-t border-slate-200 pt-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-bold text-slate-900">Review workspace</h3><button type="button" className="secondary text-xs" onClick={copyLink}>Copy invoice link ↗</button></div>
    <div className="flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1" role="group" aria-label="Invoice workspace views">{([{ id: "review", name: "Review & discuss" }, { id: "pdf", name: "Full document" }, { id: "access", name: "Access" }, { id: "questions", name: "Ask invoice" }] as const).map(item => <button key={item.id} type="button" aria-pressed={tab === item.id} onClick={() => setTab(item.id)} className={`flex-1 whitespace-nowrap rounded-lg px-3 py-2.5 text-xs font-bold ${tab === item.id ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-900"}`}>{item.name}</button>)}</div>
    {workspace.isLoading && <p role="status" className="text-sm text-slate-500">Loading collaboration…</p>}
    {workspace.isError && <p role="alert" className="text-sm text-rose-700">{workspace.error.message} <button type="button" onClick={() => workspace.refetch()} className="underline">Refresh</button></p>}
    {save.isError && <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{save.error.message} <button type="button" className="underline" onClick={() => workspace.refetch()}>Refresh invoice</button></p>}
    {notice && <p role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {data && tab === "pdf" && <section aria-label="Full invoice document"><div className="mb-3 flex flex-wrap gap-2"><a className="secondary text-xs" href={documentFileUrl(documentId)} target="_blank" rel="noreferrer">Open PDF in new tab ↗</a><a className="secondary text-xs" href={documentFileUrl(documentId, { download: true })}>Download original PDF ↓</a></div><PdfViewer documentId={documentId} /></section>}
    {data && tab === "questions" && <InvoiceQuestions documentId={documentId} />}
    {data && tab === "review" && <div className="space-y-5">
      {metadata && <MetadataForm data={data} metadata={metadata} draft={metadataDraft} categories={categories} collaborators={collaborators} saving={save.isPending} onChange={editMetadata} onSubmit={event => submit(event, "metadata")} onDiscard={() => { setMetadataDraft(null); save.reset(); void workspace.refetch(); }} />}
      <ReviewDecision data={data} status={status} reason={reason} hasDraft={Boolean(metadataDraft)} saving={save.isPending} onReasonChange={setReason} onDecide={decision => save.mutate({ action: "review", decision, comment: reason, version: data.version })} />
      <Discussion data={data} comment={comment} saving={save.isPending} onCommentChange={setComment} onSubmit={event => { event.preventDefault(); save.mutate({ action: "comments", body: comment }); }} />
      {data.reviews.length > 0 && <section><h4 className="text-sm font-bold">Decision history</h4><ol className="mt-3 space-y-3 border-l-2 border-slate-200 pl-4">{data.reviews.map(item => <li key={item.id} className="text-xs leading-5"><p><strong className="capitalize">{item.decision}</strong> · {item.actor_email}</p><p className="whitespace-pre-wrap break-words text-slate-600">{item.comment}</p><time dateTime={item.created_at} className="text-slate-400">{formatDateTime(item.created_at)}</time></li>)}</ol></section>}
    </div>}
    {data && tab === "access" && sharing && <AccessForm data={data} sharing={sharing} draft={sharingDraft} collaborators={collaborators} saving={save.isPending} onChange={editSharing} onSubmit={event => submit(event, "sharing")} onDiscard={() => { setSharingDraft(null); save.reset(); void workspace.refetch(); }} />}
  </div>;
}
