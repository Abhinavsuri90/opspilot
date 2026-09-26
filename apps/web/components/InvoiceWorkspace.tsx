"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { InvoiceQuestions } from "@/components/InvoiceQuestions";
import { PdfViewer } from "@/components/PdfViewer";
import type { components } from "@/lib/schema";

type Workspace = components["schemas"]["WorkspaceResponse"];
type MetadataDraft = { version: number; categoryId: string; reviewerId: string; originalReviewerId: string; amount: string; currency: string };
type SharingDraft = { version: number; visibility: "workspace" | "restricted"; userIds: string[] };

function metadataSnapshot(data: Workspace): MetadataDraft {
  return { version: data.version, categoryId: data.category_id ?? "", reviewerId: data.assigned_reviewer_id ?? "", originalReviewerId: data.assigned_reviewer_id ?? "", amount: data.verified_amount ?? "", currency: data.currency ?? "" };
}

function sharingSnapshot(data: Workspace): SharingDraft {
  return { version: data.version, visibility: data.visibility === "restricted" ? "restricted" : "workspace", userIds: data.grants.map(grant => grant.user_id) };
}

function errorMessage(error: unknown, status: number) {
  if (status === 409) return "This invoice changed or the action is unavailable. Refresh the invoice and try again.";
  const parsed = error as { error?: { message?: string } } | undefined;
  return parsed?.error?.message ?? "Could not save this change. Please try again.";
}

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
  const save = useMutation({ mutationFn: async (input: { action: "metadata" | "comments" | "review" | "sharing"; metadata?: MetadataDraft; sharing?: SharingDraft; decision?: "approve" | "reject" | "reopen" }) => {
    const current = workspace.data;
    if (!current) throw new Error("Load the invoice before editing it.");
    const params = { path: { document_id: documentId } };
    const metadata = input.metadata ?? metadataSnapshot(current);
    const sharing = input.sharing ?? sharingSnapshot(current);
    const result = input.action === "metadata"
      ? await api.POST("/v1/documents/{document_id}/metadata", { params, body: {
        version: metadata.version,
        category_id: metadata.categoryId || null,
        verified_amount: metadata.amount || null,
        currency: metadata.currency.toUpperCase() || null,
        ...(current.capabilities.can_assign && metadata.reviewerId !== metadata.originalReviewerId ? { assigned_reviewer_id: metadata.reviewerId || null } : {}),
      } })
      : input.action === "comments"
        ? await api.POST("/v1/documents/{document_id}/comments", { params, body: { body: comment } })
        : input.action === "review"
          ? await api.POST("/v1/documents/{document_id}/review", { params, body: { version: current.version, decision: input.decision!, comment: reason } })
          : await api.POST("/v1/documents/{document_id}/sharing", { params, body: { version: sharing.version, visibility: sharing.visibility, user_ids: sharing.userIds } });
    if (!result.data || result.error) throw new Error(errorMessage(result.error, result.response.status));
    return { workspace: result.data, action: input.action };
  }, onSuccess: async result => {
    client.setQueryData(["invoice-workspace", documentId, orgId, userId], result.workspace);
    if (result.action === "comments") setComment("");
    if (result.action === "review") setReason("");
    if (result.action === "metadata") setMetadataDraft(null);
    if (result.action === "sharing") setSharingDraft(null);
    setNotice("Changes saved.");
    await Promise.all(["document", "documents", "review-documents", "workspace-summary"].map(key => client.invalidateQueries({ queryKey: [key] })));
  }, onError: () => { setNotice(""); } });
  function submit(event: FormEvent<HTMLFormElement>, action: "metadata" | "sharing") {
    event.preventDefault();
    if (!workspace.data || save.isPending) return;
    save.mutate(action === "metadata" ? { action, metadata: metadataDraft ?? metadataSnapshot(workspace.data) } : { action, sharing: sharingDraft ?? sharingSnapshot(workspace.data) });
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
    {data && tab === "pdf" && <section aria-label="Full invoice document"><div className="mb-3 flex flex-wrap gap-2"><a className="secondary text-xs" href={`/api/v1/documents/${documentId}/file`} target="_blank" rel="noreferrer">Open PDF in new tab ↗</a><a className="secondary text-xs" href={`/api/v1/documents/${documentId}/file?download=true`}>Download original PDF ↓</a></div><PdfViewer documentId={documentId} /></section>}
    {data && tab === "questions" && <InvoiceQuestions documentId={documentId} />}
    {data && tab === "review" && <div className="space-y-5">
      {(!categories.data || !collaborators.data) && <p role={categories.isError || collaborators.isError ? "alert" : "status"} className="text-sm text-slate-500">{categories.isError || collaborators.isError ? "Could not load editing options." : "Loading editing options…"} <button type="button" onClick={() => { void categories.refetch(); void collaborators.refetch(); }} className="underline">Refresh options</button></p>}
      {categories.data && collaborators.data && metadata && <form onSubmit={event => submit(event, "metadata")} className="space-y-3 rounded-xl border border-slate-200 p-4"><h4 className="text-sm font-bold">Verified invoice details</h4><p className="text-xs leading-5 text-slate-500">Check the original document, then confirm the amount and currency. Verified amounts power your workspace totals.</p>
        {metadataDraft && <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><p>{metadataDraft.version !== data.version ? "This invoice changed while you were editing. Your draft is preserved; discard it to load the latest values before saving." : "You have unsaved invoice details. They stay here while you switch views or the invoice refreshes."}</p><button type="button" disabled={save.isPending} className="mt-2 font-semibold underline" onClick={() => { setMetadataDraft(null); save.reset(); void workspace.refetch(); }}>Discard invoice edits and load latest</button></div>}
        {(categories.isError || collaborators.isError) && <p role="alert" className="text-xs text-rose-700">Could not load all editing options. <button type="button" className="underline" onClick={() => { void categories.refetch(); void collaborators.refetch(); }}>Try again</button></p>}
        <fieldset disabled={!data.capabilities.can_edit || save.isPending} className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold">Category<select className="field mt-1 text-sm" name="category" aria-label="Category" value={metadata.categoryId} onChange={event => editMetadata({ categoryId: event.target.value })}><option value="">Uncategorized</option>{categories.data?.filter(item => item.active || item.id === metadata.categoryId).map(item => <option key={item.id} value={item.id}>{item.name}{item.active ? "" : " (archived)"}</option>)}</select></label>
          <label className="text-xs font-semibold">Assigned reviewer<select className="field mt-1 text-sm" name="reviewer" aria-label="Assigned reviewer" disabled={!data.capabilities.can_assign} value={metadata.reviewerId} onChange={event => editMetadata({ reviewerId: event.target.value })}><option value="">Unassigned</option>{metadata.reviewerId && !collaborators.data?.some(item => item.user_id === metadata.reviewerId && ["admin", "reviewer"].includes(item.role)) && <option value={metadata.reviewerId}>Current reviewer (unavailable)</option>}{collaborators.data?.filter(item => item.role === "admin" || item.role === "reviewer").map(item => <option key={item.user_id} value={item.user_id}>{item.email}</option>)}</select></label>
          <label className="text-xs font-semibold">Verified amount<input className="field mt-1 text-sm" name="amount" inputMode="decimal" pattern="[0-9]+([.][0-9]{1,4})?" placeholder="123.45" value={metadata.amount} onChange={event => editMetadata({ amount: event.target.value })} /></label>
          <label className="text-xs font-semibold">Currency (ISO code)<input className="field mt-1 text-sm uppercase" name="currency" minLength={3} maxLength={3} pattern="[A-Za-z]{3}" placeholder="USD" value={metadata.currency} onChange={event => editMetadata({ currency: event.target.value })} /></label>
        </fieldset>
        {data.capabilities.can_edit && <button className="secondary text-sm" disabled={save.isPending || !categories.data || !collaborators.data}>Save invoice details</button>}
      </form>}
      {data.capabilities.can_review && <div className="rounded-xl border border-cyan-100 bg-cyan-50/60 p-4"><h4 className="text-sm font-bold text-cyan-950">Review decision</h4>{metadataDraft && <p className="mt-2 text-xs leading-5 text-amber-900">Save or discard your invoice edits before recording a review decision.</p>}<label className="mt-3 block text-xs font-semibold" htmlFor="review-reason">Decision note (required to reject)</label><textarea id="review-reason" className="field mt-1 text-sm" maxLength={4000} rows={2} value={reason} onChange={event => setReason(event.target.value)} placeholder="What did you check or what needs correcting?" /><div className="mt-3 flex flex-wrap gap-2">{status === "needs_review" ? <><button type="button" className="primary text-sm" disabled={save.isPending || Boolean(metadataDraft) || !data.verified_amount || !data.currency} onClick={() => save.mutate({ action: "review", decision: "approve" })}>Approve invoice</button><button type="button" className="secondary text-sm !text-rose-700" disabled={save.isPending || Boolean(metadataDraft) || !reason.trim()} onClick={() => save.mutate({ action: "review", decision: "reject" })}>Reject invoice</button></> : (status === "approved" || status === "rejected") ? <button type="button" className="secondary text-sm" disabled={save.isPending || Boolean(metadataDraft)} onClick={() => save.mutate({ action: "review", decision: "reopen" })}>Reopen review</button> : <p className="text-xs text-slate-600">Review becomes available after extraction finishes.</p>}</div>{status === "needs_review" && (!data.verified_amount || !data.currency) && <p className="mt-2 text-xs text-cyan-900">Save a verified amount and currency before approving.</p>}</div>}
      <section aria-label="Invoice discussion"><h4 className="text-sm font-bold">Discussion <span className="ml-1 text-slate-400">{data.comments.length}</span></h4><div className="mt-3 max-h-80 space-y-3 overflow-auto">{data.comments.length === 0 && <p className="text-xs text-slate-500">Start a conversation about this invoice.</p>}{data.comments.map(item => <article key={item.id} className="rounded-xl bg-slate-50 p-3"><div className="flex flex-wrap justify-between gap-1 text-xs"><span className="break-all font-bold text-slate-700">{item.author_email}</span><time className="text-slate-400">{new Date(item.created_at).toLocaleString()}</time></div><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{item.body}</p></article>)}</div>{data.capabilities.can_comment && <form onSubmit={event => { event.preventDefault(); save.mutate({ action: "comments" }); }} className="mt-3 space-y-2"><label className="sr-only" htmlFor="invoice-comment">Comment on invoice</label><textarea id="invoice-comment" className="field text-sm" maxLength={4000} rows={3} value={comment} onChange={event => setComment(event.target.value)} placeholder="Add context or ask your reviewer a question…" required /><button className="secondary text-sm" disabled={save.isPending || !comment.trim()}>Post comment</button></form>}</section>
      {data.reviews.length > 0 && <section><h4 className="text-sm font-bold">Decision history</h4><ol className="mt-3 space-y-3 border-l-2 border-slate-200 pl-4">{data.reviews.map(item => <li key={item.id} className="text-xs leading-5"><p><strong className="capitalize">{item.decision}</strong> · {item.actor_email}</p><p className="whitespace-pre-wrap break-words text-slate-600">{item.comment}</p><time className="text-slate-400">{new Date(item.created_at).toLocaleString()}</time></li>)}</ol></section>}
    </div>}
    {data && tab === "access" && !collaborators.data && <p role={collaborators.isError ? "alert" : "status"} className="text-sm text-slate-500">Could not load access options yet. <button type="button" onClick={() => collaborators.refetch()} className="underline">Refresh</button></p>}
    {data && collaborators.data && sharing && tab === "access" && <form onSubmit={event => submit(event, "sharing")} className="space-y-4 rounded-xl border border-slate-200 p-4"><div><h4 className="text-sm font-bold">Document access</h4><p className="mt-1 text-xs leading-5 text-slate-500">Links require sign-in. Restricted invoices are visible to admins, the uploader, the assigned reviewer and selected teammates.</p></div>{sharingDraft && <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><p>{sharingDraft.version !== data.version ? "This invoice changed while you were editing access. Your choices are preserved; discard them to load the latest access settings." : "You have unsaved access changes."}</p><button type="button" disabled={save.isPending} className="mt-2 font-semibold underline" onClick={() => { setSharingDraft(null); save.reset(); void workspace.refetch(); }}>Discard access edits and load latest</button></div>}<fieldset disabled={!data.capabilities.can_share || save.isPending} className="space-y-3"><label className="text-xs font-semibold">Visibility<select className="field mt-1 text-sm" name="visibility" aria-label="Visibility" value={sharing.visibility} onChange={event => editSharing({ visibility: event.target.value === "restricted" ? "restricted" : "workspace" })}><option value="workspace">Everyone approved in this organization</option><option value="restricted">Only selected people</option></select></label><p className="text-xs font-semibold">Selected teammates</p>{collaborators.isError && <p role="alert" className="text-xs text-rose-700">Could not load teammates. Refresh before editing access.</p>}<div className="max-h-52 space-y-2 overflow-auto">{collaborators.data?.map(item => <label key={item.user_id} className="flex items-center gap-2 text-xs"><input type="checkbox" name="grants" value={item.user_id} checked={sharing.userIds.includes(item.user_id)} onChange={event => editSharing({ userIds: event.target.checked ? [...sharing.userIds, item.user_id] : sharing.userIds.filter(id => id !== item.user_id) })} /><span className="break-all">{item.email} <span className="text-slate-400">· {item.role}</span></span></label>)}</div>{data.capabilities.can_share && <button className="primary text-sm" disabled={save.isPending || !collaborators.data}>Save access</button>}</fieldset></form>}
  </div>;
}
