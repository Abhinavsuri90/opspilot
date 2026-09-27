"use client";

import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { ActionCard } from "@/components/actions/ActionCard";
import { ACTIONS_POLL_MS, actionStatusLabel, decisionBody, formatActionCount, HISTORY_STATUSES, rowsForTab, tabQueries, type ActionsQuery, type ActionSummary, type ActionTab } from "@/lib/actions";
import { api } from "@/lib/api";
import { apiErrorMessage, isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { usePolicies } from "@/lib/use-policies";
import { useWorkspace } from "@/lib/use-workspace";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const tabs: { id: ActionTab; label: string }[] = [
  { id: "pending", label: "Pending approvals" },
  { id: "history", label: "History" },
  { id: "dead", label: "Dead letters" },
];
const emptyCopy: Record<ActionTab, { title: string; body: string }> = {
  pending: { title: "Nothing awaits approval", body: "When an approved document proposes an action under a needs-approval policy, it appears here with a preview of exactly what will be sent." },
  history: { title: "No actions yet", body: "Executed, rejected, shadowed and forbidden actions are listed here with their attempts and outcomes." },
  dead: { title: "No dead letters", body: "Actions the worker gave up on after repeated failures land here, where a reviewer can retry them." },
};

type Mutation = { kind: "approve" | "reject" | "retry"; action: ActionSummary; comment?: string };

function queryKeyFor(orgId: string | undefined, userId: string | undefined, query: ActionsQuery) {
  return ["actions", orgId, userId, query.status ?? "all", query.document_id ?? "", query.limit] as const;
}

async function fetchActions(query: ActionsQuery): Promise<ActionSummary[]> {
  const result = await api.GET("/v1/actions", { params: { query: { status: query.status, document_id: query.document_id, limit: query.limit } } });
  if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
  if (result.error || !result.data) throw new Error("Could not load actions.");
  return result.data;
}

export default function ActionsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const session = useWorkspace();
  const orgId = session.data?.org_id;
  const userId = session.data?.user_id;
  const ready = Boolean(session.data) && !session.isError;
  const canDecide = session.data?.role === "admin" || session.data?.role === "reviewer";
  const policies = usePolicies(session.data);

  const [tab, setTab] = useState<ActionTab>("pending");
  const [documentId, setDocumentId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [notice, setNotice] = useState("");
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const deepLinkApplied = useRef(false);

  // ?document=<id> comes from a document's timeline; ?tab= from the dashboard tiles.
  useEffect(() => {
    if (deepLinkApplied.current) return;
    deepLinkApplied.current = true;
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("document");
    if (requested && UUID.test(requested)) setDocumentId(requested.toLowerCase());
    const requestedTab = params.get("tab");
    if (requestedTab === "pending" || requestedTab === "history" || requestedTab === "dead") setTab(requestedTab);
  }, []);

  const listQueries = tabQueries(tab, { statusFilter, documentId });
  const lists = useQueries({
    queries: listQueries.map(query => ({
      queryKey: queryKeyFor(orgId, userId, query),
      enabled: ready,
      queryFn: () => fetchActions(query),
      refetchInterval: ACTIONS_POLL_MS,
      placeholderData: keepPreviousData,
    })),
  });
  // The tab badges always reflect the proposals and dead letters, whichever tab is open.
  const [pendingCount, deadCount] = useQueries({
    queries: [tabQueries("pending", { documentId })[0], tabQueries("dead", { documentId })[0]].map(query => ({
      queryKey: queryKeyFor(orgId, userId, query),
      enabled: ready,
      queryFn: () => fetchActions(query),
      refetchInterval: ACTIONS_POLL_MS,
      placeholderData: keepPreviousData,
    })),
  });
  // The filter chip names the document even before any of its actions is loaded.
  const filteredDocument = useQuery({
    queryKey: ["document", documentId, orgId, userId],
    enabled: ready && documentId !== "",
    queryFn: async () => {
      const result = await api.GET("/v1/documents/{document_id}", { params: { path: { document_id: documentId } } });
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("This document is unavailable or you no longer have access to it.");
      return result.data;
    },
  });
  const listError = lists.find(list => list.isError)?.error;
  useEffect(() => {
    if (isUnauthorizedError(listError)) {
      client.clear();
      router.replace("/login");
    }
  }, [listError, client, router]);

  const invalidate = () => Promise.all(["actions", "action", "document", "documents", "timeline", "workspace-summary", "review-queue"].map(key => client.invalidateQueries({ queryKey: [key] })));

  const mutate = useMutation({
    mutationFn: async (input: Mutation) => {
      if (input.kind === "retry") {
        const result = await api.POST("/v1/actions/{action_id}/retry", { params: { path: { action_id: input.action.id } }, body: { version: input.action.version } });
        if (result.response.status === 401) throw unauthorizedError();
        if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, result.response.status === 409 ? "This action changed since you loaded it; the list has been refreshed." : "Could not retry this action."));
        return result.data;
      }
      const prepared = decisionBody(input.action, input.kind, input.comment ?? "");
      if ("error" in prepared) throw new Error(prepared.error);
      const result = await api.POST("/v1/actions/{action_id}/decision", { params: { path: { action_id: input.action.id } }, body: prepared.body });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, result.response.status === 409 ? "This action changed since you loaded it; the list has been refreshed." : "Could not record the decision."));
      return result.data;
    },
    onSuccess: (saved, input) => {
      setRowErrors(current => { const next = { ...current }; delete next[input.action.id]; return next; });
      setNotice(input.kind === "approve" ? `Approved ${saved.action_type.replaceAll("_", " ")} for ${saved.filename}. The worker executes it next.` : input.kind === "reject" ? `Rejected ${saved.action_type.replaceAll("_", " ")} for ${saved.filename}.` : `Retry queued for ${saved.filename}.`);
      void invalidate();
    },
    onError: (error, input) => {
      if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); return; }
      setNotice("");
      setRowErrors(current => ({ ...current, [input.action.id]: error.message }));
      void client.invalidateQueries({ queryKey: ["actions"] });
    },
  });

  if (session.isError || !session.data || isUnauthorizedError(listError)) return <SessionFallback session={session} />;

  const rows = rowsForTab(tab, lists.map(list => list.data ?? []));
  const loading = lists.some(list => list.isPending);
  const failed = lists.find(list => list.isError && !isUnauthorizedError(list.error));
  const filteredFilename = documentId ? filteredDocument.data?.filename ?? [pendingCount.data, deadCount.data, ...lists.map(list => list.data)].flatMap(list => list ?? []).find(action => action.document_id === documentId)?.filename : undefined;
  const busyId = mutate.isPending ? mutate.variables.action.id : null;
  const counts: Record<ActionTab, string | null> = { pending: formatActionCount(pendingCount.data?.length), history: null, dead: formatActionCount(deadCount.data?.length) };

  return <AppShell session={session.data} active="actions">
    <div className="mb-6">
      <p className="text-[11px] font-bold uppercase tracking-[.18em] text-cyan-700">Agent</p>
      <h1 className="mt-2 text-3xl font-bold tracking-[-.04em] text-[#12233d] sm:text-[38px]">Actions</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Every external side effect the agent proposes for an approved document, with the exact payload, who decided it, and what the destination answered. Refreshes every 10 seconds.</p>
    </div>

    {policies.data?.shadow_mode && <p role="status" className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><span className="font-bold">Shadow mode is on.</span> Approved actions are recorded as shadowed and never reach a connector. Turn it off in <Link href="/settings/policies" className="font-semibold underline">Policies</Link>.</p>}
    {!canDecide && <p className="mb-4 rounded-xl bg-blue-50 p-4 text-sm text-blue-900">You can follow actions on documents you have access to. Approving, rejecting and retrying require a reviewer or administrator account.</p>}
    {documentId && <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50/60 px-4 py-3 text-sm text-cyan-950" data-testid="document-filter">
      <span>Showing actions for <span className="break-all font-semibold">{filteredFilename ?? documentId}</span></span>
      <Link href={`/review/${encodeURIComponent(documentId)}`} className="font-semibold text-[#11627a] hover:underline">Open document</Link>
      <button type="button" className="ml-auto rounded-lg border border-cyan-300 px-2.5 py-1 text-xs font-semibold" onClick={() => { setDocumentId(""); window.history.replaceState(null, "", "/actions"); }}>Show all documents</button>
    </div>}

    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200">
      <div role="tablist" aria-label="Action lists" className="flex gap-1 overflow-x-auto">
        {tabs.map(item => <button key={item.id} id={`actions-tab-${item.id}`} type="button" role="tab" tabIndex={tab === item.id ? 0 : -1} aria-selected={tab === item.id} aria-controls="actions-panel" onClick={() => { setTab(item.id); setNotice(""); }} onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const index = tabs.findIndex(candidate => candidate.id === tab);
          const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : event.key === "ArrowRight" ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length;
          setTab(tabs[next].id);
          document.getElementById(`actions-tab-${tabs[next].id}`)?.focus();
        }} className={`whitespace-nowrap border-b-2 px-3 py-3 text-sm font-semibold ${tab === item.id ? "border-[#11627a] text-[#11627a]" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
          {item.label}{counts[item.id] !== null && counts[item.id] !== "—" && counts[item.id] !== "0" && <span className={`ml-2 rounded-full px-2 py-0.5 text-[11px] ${item.id === "dead" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800"}`} data-testid={`count-${item.id}`}>{counts[item.id]}</span>}
        </button>)}
      </div>
      {tab === "history" && <label className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-600">Status
        <select aria-label="Filter history by status" className="field !w-auto !py-1.5 !text-sm" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}>
          <option value="">All outcomes</option>
          {HISTORY_STATUSES.map(status => <option key={status} value={status}>{actionStatusLabel(status)}</option>)}
        </select>
      </label>}
    </div>

    <section id="actions-panel" role="tabpanel" aria-labelledby={`actions-tab-${tab}`} className="mt-5 space-y-4">
      {notice && <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
      {failed && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{failed.error?.message ?? "Could not load actions."} <button type="button" className="font-bold underline" onClick={() => lists.forEach(list => list.refetch())}>Try again</button></p>}
      {loading && !failed && <p role="status" className="text-sm text-slate-500">Loading actions…</p>}
      {!loading && !failed && rows.length === 0 && <div className="card px-6 py-12 text-center">
        <div aria-hidden="true" className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-slate-50 text-2xl text-slate-500">⇢</div>
        <h2 className="mt-4 font-semibold text-slate-800">{emptyCopy[tab].title}</h2>
        <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-slate-500">{emptyCopy[tab].body}</p>
      </div>}
      {rows.map(action => <ActionCard
        key={action.id}
        action={action}
        variant={tab}
        canDecide={canDecide}
        paused={Boolean(policies.data?.kill_switch)}
        busy={busyId === action.id}
        error={rowErrors[action.id] ?? null}
        onApprove={target => { setNotice(""); mutate.mutate({ kind: "approve", action: target }); }}
        onReject={(target, reason) => { setNotice(""); mutate.mutate({ kind: "reject", action: target, comment: reason }); }}
        onRetry={target => { setNotice(""); mutate.mutate({ kind: "retry", action: target }); }}
      />)}
      {rows.length >= 100 && <p className="text-xs text-slate-500">Showing the 100 most recent. Narrow the list by document from its timeline.</p>}
    </section>
  </AppShell>;
}
