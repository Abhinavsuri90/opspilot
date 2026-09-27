"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { KillSwitchDialog } from "@/components/settings/KillSwitchDialog";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { Switch } from "@/components/settings/Switch";
import { actionTypeLabel, policyModeLabel } from "@/lib/actions";
import { api } from "@/lib/api";
import { connectorActionTypes, connectorTypeLabels, type ConnectorType } from "@/lib/connectors";
import { apiErrorMessage, isUnauthorizedError, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { buildPoliciesUpdate, isPolicyMode, POLICY_MODES, policyDraftReducer, policyModeDescriptions, policyRows, type PolicyChanges, type PolicyDraft } from "@/lib/policies";
import { policiesQueryKey, usePolicies } from "@/lib/use-policies";
import { useWorkspace } from "@/lib/use-workspace";

const connectorForAction = Object.fromEntries(Object.entries(connectorActionTypes).map(([connector, action]) => [action, connector])) as Record<string, ConnectorType>;

export default function PoliciesSettingsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const session = useWorkspace();
  const isAdmin = session.data?.role === "admin";
  const policies = usePolicies(session.data);
  const [draft, setDraft] = useState<PolicyDraft>({});
  const [dialog, setDialog] = useState<{ engaging: boolean } | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<string | null>(null);

  // A refresh (poll, or another administrator's save) drops draft choices it already reflects.
  useEffect(() => {
    if (policies.data) setDraft(current => policyDraftReducer(current, { type: "synced", server: policies.data }));
  }, [policies.data]);
  useEffect(() => {
    if (isUnauthorizedError(policies.error)) { client.clear(); router.replace("/login"); }
  }, [policies.error, client, router]);

  const save = useMutation({
    mutationFn: async (changes: PolicyChanges) => {
      const server = policies.data;
      if (!server) throw new Error("Load the settings before changing them.");
      const body = buildPoliciesUpdate(server, changes);
      if (!body) return server;
      const result = await api.POST("/v1/settings/policies", { body });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) {
        const status = result.response.status;
        if (status === 409) await policies.refetch();
        throw new Error(apiErrorMessage(result.error, status, status === 409 ? "Settings changed since you loaded them. They have been refreshed; review and try again." : "Could not save the settings."));
      }
      return result.data;
    },
    onSuccess: (saved, changes) => {
      client.setQueryData(policiesQueryKey(session.data), saved);
      setError(null);
      setDialog(null);
      if (changes.policies) setDraft({});
      setNotice(changes.killSwitch !== undefined ? (changes.killSwitch ? "Agent paused. Nothing executes until you resume it." : "Agent resumed. Waiting actions execute within about a minute.")
        : changes.shadowMode !== undefined ? (changes.shadowMode ? "Shadow mode on: approved actions are recorded, not executed." : "Shadow mode off: approved actions execute again.")
        : `Policies saved as version ${saved.version}.`);
      void client.invalidateQueries({ queryKey: ["actions"] });
    },
    onError: error => {
      if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); return; }
      setNotice("");
      setError(error.message);
    },
  });

  if (session.isError || !session.data || isUnauthorizedError(policies.error)) return <SessionFallback session={session} />;
  if (!isAdmin) return <AppShell session={session.data} active="policies"><AdminOnly description="Only organization administrators can pause the agent, switch shadow mode or change action policies." /></AppShell>;

  const server = policies.data;
  const rows = server ? policyRows(server, draft) : [];
  const dirtyCount = rows.filter(row => row.dirty).length;

  return <AppShell session={session.data} active="policies">
    <SettingsHeader active="policies" title="Policies" description="The agent's safety controls: an emergency stop, a rehearsal mode, and the approval rule for each kind of external action. Every change is audited with your account." />

    {policies.isPending && <p role="status" className="text-sm text-slate-500">Loading settings…</p>}
    {policies.isError && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{policies.error.message} <button type="button" className="font-bold underline" onClick={() => policies.refetch()}>Try again</button></p>}
    {notice && <p role="status" className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
    {error && !dialog && <p role="alert" className="mb-4 rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{error}</p>}

    {server && <div className="grid min-w-0 gap-5 lg:grid-cols-2">
      <section aria-labelledby="kill-switch-heading" className={`card p-5 ${server.kill_switch ? "!border-rose-300 ring-2 ring-rose-200" : ""}`}>
        <h2 id="kill-switch-heading" className="sr-only">Kill switch</h2>
        <Switch
          label="Kill switch"
          tone="danger"
          checked={server.kill_switch}
          disabled={save.isPending}
          badge={server.kill_switch ? <span className="rounded-full bg-rose-700 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">Engaged · agent paused</span> : <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-emerald-800 ring-1 ring-emerald-200">Off · agent running</span>}
          description={<>Stops every external action immediately, including ones already approved. The worker re-checks this switch right before each execution, so nothing slips through. Waiting actions resume when you turn it off. <Link href="/actions" className="font-semibold text-[#11627a] underline">See queued actions</Link>.</>}
          onChange={next => { setError(null); setDialog({ engaging: next }); }}
        />
      </section>

      <section aria-labelledby="shadow-heading" className="card p-5">
        <h2 id="shadow-heading" className="sr-only">Shadow mode</h2>
        <Switch
          label="Shadow mode"
          checked={server.shadow_mode}
          disabled={save.isPending}
          badge={server.shadow_mode ? <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-amber-800">On</span> : null}
          description="A rehearsal: actions are proposed, approved and recorded exactly as normal, but instead of calling the connector the worker marks them shadowed. Use it to check payloads and policies against real documents before going live."
          onChange={next => { setError(null); save.mutate({ shadowMode: next }); }}
        />
      </section>
    </div>}

    {server && <section aria-labelledby="policies-heading" className="card mt-5 overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-5">
        <div><h2 id="policies-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Action policies</h2><p className="mt-1 text-xs leading-5 text-slate-500">What happens when an approved document proposes each kind of action. The workflow configuration sets a default; a choice here overrides it for this organization.</p></div>
        <dl className="text-xs text-slate-500"><dt className="sr-only">Audit</dt><dd>Version {server.version} · changed {formatDateTime(server.updated_at)}{server.updated_by_email ? <> by <span className="break-all font-semibold text-slate-700">{server.updated_by_email}</span></> : ""}</dd></dl>
      </div>
      <form onSubmit={event => { event.preventDefault(); if (dirtyCount > 0 && !save.isPending) { setNotice(""); save.mutate({ policies: draft }); } }}>
        <ul className="divide-y divide-slate-100" aria-label="Policy per action type">
          {rows.map(row => {
            const connector = connectorForAction[row.actionType];
            return <li key={row.actionType} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)] sm:items-center" data-action-type={row.actionType} data-dirty={row.dirty || undefined}>
              <div className="min-w-0">
                <p className="text-sm font-bold capitalize text-slate-900">{actionTypeLabel(row.actionType)}</p>
                <p className="mt-0.5 text-xs text-slate-500">{connector ? `${connectorTypeLabels[connector]} connector` : row.actionType}{row.dirty && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-800">Unsaved</span>}</p>
              </div>
              <div className="text-xs text-slate-600">
                <p><span className="font-semibold text-slate-500">Default from config:</span> {row.configDefault ? policyModeLabel(row.configDefault) : <span className="text-slate-400">none (needs approval)</span>}</p>
                <p className="mt-0.5"><span className="font-semibold text-slate-500">In effect:</span> {policyModeLabel(row.effective)}{row.source === "override" && <span className="ml-1 rounded-full bg-cyan-50 px-1.5 py-0.5 text-[10px] font-bold text-cyan-800 ring-1 ring-cyan-200">override</span>}</p>
              </div>
              <div>
                <label htmlFor={`policy-${row.actionType}`} className="sr-only">Policy for {actionTypeLabel(row.actionType)}</label>
                <select id={`policy-${row.actionType}`} className="field !py-2 text-sm" value={row.selected} disabled={save.isPending} onChange={event => { const mode = event.target.value; if (isPolicyMode(mode)) { setNotice(""); setDraft(current => policyDraftReducer(current, { type: "choose", actionType: row.actionType, mode }, server)); } }}>
                  {POLICY_MODES.map(mode => <option key={mode} value={mode}>{policyModeLabel(mode)}</option>)}
                </select>
                <p className="mt-1 text-[11px] leading-4 text-slate-500">{policyModeDescriptions[row.selected]}</p>
              </div>
            </li>;
          })}
        </ul>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/60 px-5 py-4">
          <p className="text-xs text-slate-500">{dirtyCount === 0 ? "No unsaved changes." : `${dirtyCount} change${dirtyCount === 1 ? "" : "s"} to save.`} Saving sends only the rows you changed, against version {server.version}.</p>
          <div className="flex gap-2">
            <button type="button" className="secondary !min-h-10 text-sm" disabled={dirtyCount === 0 || save.isPending} onClick={() => setDraft({})}>Discard</button>
            <button type="submit" className="primary !min-h-10 text-sm" disabled={dirtyCount === 0 || save.isPending}>{save.isPending && save.variables?.policies ? "Saving…" : "Save policies"}</button>
          </div>
        </div>
      </form>
    </section>}

    {dialog && <KillSwitchDialog engaging={dialog.engaging} saving={save.isPending} error={error} onConfirm={() => { setNotice(""); save.mutate({ killSwitch: dialog.engaging }); }} onClose={() => { if (!save.isPending) { setDialog(null); setError(null); } }} />}
  </AppShell>;
}
