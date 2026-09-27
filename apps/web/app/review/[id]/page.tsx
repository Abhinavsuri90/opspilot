"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { InvoiceQuestions } from "@/components/InvoiceQuestions";
import { PdfViewer, type PdfHighlight } from "@/components/PdfViewer";
import { SessionFallback } from "@/components/SessionFallback";
import { StatusBadge } from "@/components/StatusBadge";
import { DecisionPanel } from "@/components/review/DecisionPanel";
import { Dialog } from "@/components/review/Dialog";
import { FieldList } from "@/components/review/FieldList";
import { RuleResults } from "@/components/review/RuleResults";
import { ShortcutsDialog } from "@/components/review/ShortcutsDialog";
import { SlaChip } from "@/components/review/SlaChip";
import { Timeline } from "@/components/review/Timeline";
import { AccessForm } from "@/components/workspace/AccessForm";
import { Discussion } from "@/components/workspace/Discussion";
import { saveMessage, sendSave, type SaveInput } from "@/components/workspace/save";
import { sharingSnapshot, type Decision, type SharingDraft } from "@/components/workspace/types";
import { api } from "@/lib/api";
import { isDocumentInProgress } from "@/lib/document-status";
import { isUnauthorizedError, unauthorizedError } from "@/lib/errors";
import { summarizeFieldStatuses, type FieldDetail } from "@/lib/fields";
import { keyContext, reviewShortcut } from "@/lib/review-keys";
import { useNow } from "@/lib/use-now";
import { useWorkspace } from "@/lib/use-workspace";
import { documentFileUrl } from "@/lib/urls";

type Tab = "discussion" | "access" | "timeline" | "questions";
type Correction = { fieldId: string; action: "accept" | "edit"; value?: string };

const tabs: { id: Tab; label: string }[] = [
  { id: "discussion", label: "Discussion" },
  { id: "access", label: "Access" },
  { id: "timeline", label: "Timeline" },
  { id: "questions", label: "Ask invoice" },
];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function ReviewDocumentPage() {
  const params = useParams<{ id: string }>();
  const documentId = typeof params?.id === "string" && UUID.test(params.id) ? params.id.toLowerCase() : "";
  const router = useRouter();
  const client = useQueryClient();
  const session = useWorkspace();
  const orgId = session.data?.org_id;
  const userId = session.data?.user_id;
  const ready = Boolean(session.data) && !session.isError && documentId !== "";
  const now = useNow(30_000);

  const [focusedIndex, setFocusedIndex] = useState(-1);
  const [focusTick, setFocusTick] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<{ fieldId: string; message: string } | null>(null);
  const [highlight, setHighlight] = useState<(PdfHighlight & { fieldId: string }) | null>(null);
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [sharingDraft, setSharingDraft] = useState<SharingDraft | null>(null);
  const [tab, setTab] = useState<Tab>("discussion");
  const [approveOpen, setApproveOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);

  const detailKey = ["document", documentId, orgId, userId];
  const workspaceKey = ["invoice-workspace", documentId, orgId, userId];
  const detail = useQuery({
    queryKey: detailKey,
    enabled: ready,
    queryFn: async () => {
      const result = await api.GET("/v1/documents/{document_id}", { params: { path: { document_id: documentId } } });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.response.status === 404 || result.response.status === 403) throw new Error("This invoice is unavailable or you no longer have access to it.");
      if (result.error || !result.data) throw new Error("Could not load this invoice.");
      return result.data;
    },
    refetchInterval: query => {
      if (query.state.status === "error") return false;
      const status = query.state.data?.status;
      return status !== undefined && isDocumentInProgress(status) ? 2000 : 15000;
    },
  });
  const workspace = useQuery({
    queryKey: workspaceKey,
    enabled: ready && Boolean(detail.data),
    queryFn: async () => {
      const result = await api.GET("/v1/documents/{document_id}/workspace", { params: { path: { document_id: documentId } } });
      if (!result.data || result.error) throw new Error("Could not load invoice collaboration. Your access may have changed.");
      return result.data;
    },
    refetchInterval: 15_000,
  });
  const collaborators = useQuery({ queryKey: ["collaborators", orgId, userId], enabled: ready, queryFn: async () => { const result = await api.GET("/v1/organization/collaborators"); if (!result.data || result.error) throw new Error("Could not load teammates"); return result.data; } });
  const timeline = useQuery({
    queryKey: ["timeline", documentId, orgId, userId],
    enabled: ready && tab === "timeline" && Boolean(detail.data),
    queryFn: async () => {
      const result = await api.GET("/v1/documents/{document_id}/timeline", { params: { path: { document_id: documentId } } });
      if (!result.data || result.error) throw new Error("Could not load the timeline");
      return result.data;
    },
  });
  useEffect(() => {
    if (isUnauthorizedError(detail.error)) {
      client.clear();
      router.replace("/login");
    }
  }, [detail.error, client, router]);

  const invalidateAfterChange = () => Promise.all(["document", "documents", "review-queue", "workspace-summary", "timeline", "invoice-workspace"].map(key => client.invalidateQueries({ queryKey: [key] })));

  const correct = useMutation({
    mutationFn: async (input: Correction) => {
      const current = detail.data;
      if (!current) throw new Error("Load the invoice before editing it.");
      const result = await api.POST("/v1/documents/{document_id}/fields/{field_id}", {
        params: { path: { document_id: documentId, field_id: input.fieldId } },
        body: { version: current.version, action: input.action, value: input.action === "edit" ? input.value ?? "" : undefined },
      });
      if (result.response.status === 401) throw unauthorizedError();
      if (!result.data || result.error) throw new Error(saveMessage(result.error, result.response.status));
      return result.data;
    },
    // Invalidation is not awaited: a mutation stays pending until onSuccess
    // settles, and the next keyboard action must not be swallowed meanwhile.
    onSuccess: saved => {
      client.setQueryData(detailKey, saved);
      setEditingId(null);
      setFieldError(null);
      setNotice("Field saved.");
      setFocusTick(tick => tick + 1);
      void invalidateAfterChange();
    },
    onError: (error, input) => {
      if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); return; }
      setFieldError({ fieldId: input.fieldId, message: error.message });
    },
  });
  const save = useMutation({
    mutationFn: async (input: SaveInput) => {
      const current = workspace.data;
      if (!current) throw new Error("Load the invoice before editing it.");
      const result = await sendSave(documentId, current, input);
      if (!result.data || result.error) throw new Error(saveMessage(result.error, result.response.status));
      return result.data;
    },
    onSuccess: (saved, input) => {
      client.setQueryData(workspaceKey, saved);
      if (input.action === "comments") setComment("");
      if (input.action === "sharing") setSharingDraft(null);
      if (input.action === "review") { setReason(""); setDecisionError(null); setApproveOpen(false); }
      setNotice(input.action === "review" ? `Decision recorded: ${input.decision}.` : "Changes saved.");
      void invalidateAfterChange();
    },
    onError: (error, input) => {
      setNotice("");
      if (input.action === "review") { setDecisionError(error.message); setApproveOpen(false); }
    },
  });

  const fields: FieldDetail[] = detail.data?.fields ?? [];
  const status = detail.data?.status ?? "";
  const canReview = Boolean(workspace.data?.capabilities.can_review);
  const canAct = canReview && status === "needs_review";
  const flaggedCount = detail.data?.flagged_count ?? 0;
  const canApprove = canAct && flaggedCount === 0 && !save.isPending;
  const dialogOpen = approveOpen || shortcutsOpen;

  function focusField(index: number) { setFocusedIndex(index); setFocusTick(tick => tick + 1); }
  function accept(field: FieldDetail) { if (!canAct || correct.isPending) return; setFieldError(null); correct.mutate({ fieldId: field.id, action: "accept" }); }
  function startEdit(field: FieldDetail) { if (!canAct) return; setFieldError(null); setEditingId(field.id); }
  function cancelEdit() { setEditingId(null); setFieldError(null); setFocusTick(tick => tick + 1); }
  function saveEdit(field: FieldDetail, value: string) { if (!canAct || correct.isPending) return; correct.mutate({ fieldId: field.id, action: "edit", value }); }
  function findEvidence(field: FieldDetail) {
    setHighlight({ fieldId: field.id, page: field.page_number, text: field.evidence });
    if (window.innerWidth < 1024) document.getElementById("review-document-pane")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function decide(decision: Decision) {
    const version = detail.data?.version;
    if (version === undefined) return;
    setDecisionError(null);
    save.mutate({ action: "review", decision, comment: reason, version });
  }
  function requestApprove() {
    if (!canAct) return;
    if (flaggedCount > 0) { setNotice(`${flaggedCount} field(s) still need review`); return; }
    setApproveOpen(true);
  }

  // The keyboard handler reads the latest state through a ref, so one listener
  // lives for the whole page instead of resubscribing on every render.
  const handleKey = useRef<(event: KeyboardEvent) => void>(() => undefined);
  useEffect(() => {
    handleKey.current = event => {
      const action = reviewShortcut(keyContext(event, dialogOpen), { focusedIndex, fieldCount: fields.length });
      if (action.type === "none") return;
      if (action.type === "move") { event.preventDefault(); focusField(action.index); return; }
      if (action.type === "accept") { event.preventDefault(); const field = fields[action.index]; if (field && (field.status === "auto" || field.status === "needs_review")) accept(field); return; }
      if (action.type === "edit") { event.preventDefault(); const field = fields[action.index]; if (field) startEdit(field); return; }
      if (action.type === "approve") { if (!canReview || status !== "needs_review") return; event.preventDefault(); requestApprove(); return; }
      if (action.type === "reject") { if (!reasonRef.current) return; event.preventDefault(); reasonRef.current.focus(); reasonRef.current.scrollIntoView({ block: "center" }); return; }
      if (action.type === "toggle-shortcuts") { event.preventDefault(); setShortcutsOpen(open => !open); return; }
      if (action.type === "close-dialog") { event.preventDefault(); setShortcutsOpen(false); setApproveOpen(false); return; }
      if (action.type === "cancel-edit" && editingId) { event.preventDefault(); cancelEdit(); }
    };
  });
  useEffect(() => {
    const listener = (event: KeyboardEvent) => handleKey.current(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  if (session.isError || !session.data || isUnauthorizedError(detail.error)) return <SessionFallback session={session} />;
  const data = workspace.isError ? undefined : workspace.data;
  const sharing = sharingDraft ?? (data ? sharingSnapshot(data) : null);
  const assignee = data?.assigned_reviewer_id ? collaborators.data?.find(item => item.user_id === data.assigned_reviewer_id)?.email ?? "Assigned reviewer" : "Unassigned";
  const summary = summarizeFieldStatuses(fields);
  const highlightedId = highlight?.fieldId ?? null;

  return <AppShell session={session.data} active="review">
    <div className="mx-auto max-w-[1440px] space-y-4 pb-10">
      <Link href="/review" className="inline-flex items-center gap-1 text-sm font-semibold text-blue-700 hover:underline"><span aria-hidden="true">←</span> Back to queue</Link>
      {!documentId && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">This review link is not valid.</p>}
      {detail.isLoading && documentId && <p role="status" className="text-sm text-slate-500">Loading invoice…</p>}
      {detail.isError && !isUnauthorizedError(detail.error) && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{detail.error.message} <button type="button" className="font-bold underline" onClick={() => detail.refetch()}>Try again</button></p>}

      {detail.data && <>
        <header className="card flex flex-wrap items-start justify-between gap-4 p-5">
          <div className="min-w-0 flex-1">
            <p className="eyebrow">Review · {detail.data.document_type.replaceAll("_", " ")}</p>
            <h1 className="mt-1 break-all text-2xl font-bold tracking-tight text-slate-900">{detail.data.filename}</h1>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <StatusBadge status={detail.data.status} />
              {detail.data.review_task && <SlaChip dueAt={detail.data.review_task.due_at} completedAt={detail.data.review_task.completed_at} outcome={detail.data.review_task.outcome} now={now} />}
              <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 font-semibold">Assignee: <span className="break-all">{assignee}</span></span>
              <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 font-semibold" data-testid="field-summary">{summary.flagged} flagged · {summary.auto} auto · {summary.corrected} corrected{summary.accepted > 0 ? ` · ${summary.accepted} accepted` : ""}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="secondary text-xs" onClick={() => setShortcutsOpen(true)} aria-haspopup="dialog">Shortcuts <kbd className="rounded bg-slate-100 px-1 font-mono text-[10px]">?</kbd></button>
            <Link href={`/inbox?document=${encodeURIComponent(documentId)}`} className="secondary text-xs">Open in inbox</Link>
          </div>
        </header>
        {!canReview && workspace.isSuccess && <p className="rounded-xl bg-blue-50 p-4 text-sm text-blue-900">You can inspect invoices you have access to. Review decisions require an admin or reviewer account.</p>}
        {isDocumentInProgress(detail.data.status) && <p role="status" className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">Extraction is running. This page updates automatically.</p>}
        {detail.data.failure_reason && <p role="alert" className="rounded-xl border border-rose-100 bg-rose-50 p-4 text-sm text-rose-800">{detail.data.failure_reason}</p>}
        {notice && <p role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
        {workspace.isError && <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{workspace.error.message} <button type="button" className="underline" onClick={() => workspace.refetch()}>Refresh</button></p>}

        <div className="grid min-w-0 gap-5 lg:grid-cols-2 lg:items-start">
          <section id="review-document-pane" aria-label="Invoice document" className="card min-w-0 p-4 lg:sticky lg:top-6">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-bold text-slate-900">Document</h2><div className="flex gap-2"><a className="secondary min-h-8 px-2.5 text-[11px]" href={documentFileUrl(documentId)} target="_blank" rel="noreferrer">Open PDF ↗</a><a className="secondary min-h-8 px-2.5 text-[11px]" href={documentFileUrl(documentId, { download: true })}>Download ↓</a></div></div>
            <PdfViewer documentId={documentId} highlight={highlight} />
          </section>

          <section aria-label="Review fields" className="min-w-0 space-y-4 lg:max-h-[calc(100vh-7rem)] lg:overflow-y-auto lg:pr-1">
            <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-bold text-slate-900">Fields <span className="ml-1 text-slate-400">{fields.length}</span></h2><p className="text-[11px] font-semibold text-slate-500">J/K move · Enter accept · E edit</p></div>
            <FieldList fields={fields} focusedIndex={focusedIndex} focusTick={focusTick} editingId={editingId} savingId={correct.isPending ? correct.variables.fieldId : null} error={fieldError} canAct={canAct} highlightedId={highlightedId} onFocusIndex={setFocusedIndex} onAccept={accept} onStartEdit={startEdit} onCancelEdit={cancelEdit} onSaveEdit={saveEdit} onFindEvidence={findEvidence} />
            <RuleResults rules={detail.data.rule_results} />
            <DecisionPanel status={detail.data.status} canReview={canReview} flaggedCount={flaggedCount} reason={reason} saving={save.isPending} error={decisionError} reasonRef={reasonRef} onReasonChange={setReason} onApprove={requestApprove} onReject={() => decide("reject")} onReopen={() => decide("reopen")} />

            <div className="card overflow-hidden">
              <div className="flex gap-1 overflow-x-auto border-b border-slate-200 px-2" role="tablist" aria-label="Invoice collaboration">
                {tabs.map(item => <button key={item.id} id={`review-tab-${item.id}`} type="button" role="tab" tabIndex={tab === item.id ? 0 : -1} aria-selected={tab === item.id} aria-controls={`review-panel-${item.id}`} onClick={() => setTab(item.id)} onKeyDown={event => {
                  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                  event.preventDefault();
                  const index = tabs.findIndex(candidate => candidate.id === tab);
                  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : event.key === "ArrowRight" ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length;
                  setTab(tabs[next].id);
                  document.getElementById(`review-tab-${tabs[next].id}`)?.focus();
                }} className={`whitespace-nowrap border-b-2 px-3 py-3 text-sm font-semibold ${tab === item.id ? "border-[#11627a] text-[#11627a]" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{item.label}{item.id === "discussion" && data && data.comments.length > 0 && <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{data.comments.length}</span>}</button>)}
              </div>
              <div id={`review-panel-${tab}`} role="tabpanel" aria-labelledby={`review-tab-${tab}`} className="p-4">
                {workspace.isLoading && tab !== "timeline" && <p role="status" className="text-sm text-slate-500">Loading collaboration…</p>}
                {save.isError && save.variables.action !== "review" && tab !== "timeline" && <p role="alert" className="mb-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{save.error.message}</p>}
                {data && tab === "discussion" && <Discussion data={data} comment={comment} saving={save.isPending} onCommentChange={setComment} onSubmit={event => { event.preventDefault(); save.mutate({ action: "comments", body: comment }); }} />}
                {data && sharing && tab === "access" && <AccessForm data={data} sharing={sharing} draft={sharingDraft} collaborators={collaborators} saving={save.isPending} onChange={values => { if (sharing) setSharingDraft({ ...sharing, ...values }); }} onSubmit={event => { event.preventDefault(); if (!save.isPending) save.mutate({ action: "sharing", sharing }); }} onDiscard={() => { setSharingDraft(null); save.reset(); void workspace.refetch(); }} />}
                {tab === "timeline" && <Timeline entries={timeline.data} isLoading={timeline.isLoading} isError={timeline.isError} refetch={timeline.refetch} />}
                {tab === "questions" && <InvoiceQuestions documentId={documentId} />}
              </div>
            </div>
          </section>
        </div>
      </>}
    </div>

    {approveOpen && <Dialog title="Approve this invoice?" description="Approval records your decision note, closes the review task and uses the verified amount for workspace totals." onClose={() => setApproveOpen(false)} testId="approve-dialog">
      <p className="text-sm text-slate-700"><span className="font-semibold">{detail.data?.filename}</span>{reason.trim() ? <> · note: “{reason.trim()}”</> : " · no decision note"}</p>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" className="secondary text-sm" onClick={() => setApproveOpen(false)} disabled={save.isPending}>Cancel</button>
        <button type="button" className="primary text-sm" onClick={() => decide("approve")} disabled={save.isPending || !canApprove}>{save.isPending ? "Approving…" : "Confirm approval"}</button>
      </div>
    </Dialog>}
    {shortcutsOpen && <ShortcutsDialog onClose={() => setShortcutsOpen(false)} />}
  </AppShell>;
}
