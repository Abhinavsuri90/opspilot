"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { actionTypeLabel, policyModeLabel } from "@/lib/actions";
import { api } from "@/lib/api";
import { isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { BASELINE_MINUTES, describeWorkflowFailure, lineRange, MAX_WORKFLOW_YAML_BYTES, setTopLevelScalar, SLA_MINUTES, summarizeWorkflow, workflowFilename, workflowScalars, yamlByteLength, type WorkflowFailure, type WorkflowResponse } from "@/lib/workflow";
import { useWorkspace } from "@/lib/use-workspace";

function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/yaml" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function WorkflowSettingsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const session = useWorkspace();
  const isAdmin = session.data?.role === "admin";
  const key = ["workflow", session.data?.org_id, session.data?.user_id];
  const workflow = useQuery({
    queryKey: key,
    enabled: isAdmin,
    queryFn: async (): Promise<WorkflowResponse> => {
      const result = await api.GET("/v1/settings/workflow");
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load the workflow configuration.");
      return result.data;
    },
  });
  const [text, setText] = useState<string | null>(null);
  const [failure, setFailure] = useState<WorkflowFailure | null>(null);
  const [notice, setNotice] = useState("");
  const [importError, setImportError] = useState("");
  const editor = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // The editor starts from the saved YAML once; later refetches never overwrite unsaved edits.
  useEffect(() => {
    if (workflow.data && text === null) setText(workflow.data.yaml);
  }, [workflow.data, text]);
  useEffect(() => {
    if (isUnauthorizedError(workflow.error)) { client.clear(); router.replace("/login"); }
  }, [workflow.error, client, router]);

  const save = useMutation({
    mutationFn: async () => {
      if (!workflow.data || text === null) throw new Error("Load the workflow before saving it.");
      if (yamlByteLength(text) > MAX_WORKFLOW_YAML_BYTES) throw new Error("The YAML is larger than 64 KB.");
      const result = await api.POST("/v1/settings/workflow", { body: { base_version: workflow.data.version, yaml: text } });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) {
        const described = describeWorkflowFailure(result.error, result.response.status);
        if (described.conflict) await client.invalidateQueries({ queryKey: ["workflow"] });
        setFailure(described);
        throw new Error(described.message);
      }
      return result.data;
    },
    onSuccess: saved => {
      client.setQueryData(key, saved);
      setText(saved.yaml);
      setFailure(null);
      setNotice(`Saved as version ${saved.version}. New documents use it from now on; documents already extracted keep the version they were pinned to.`);
      void client.invalidateQueries({ queryKey: ["policies"] });
    },
    onError: error => {
      if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); return; }
      setNotice("");
      setFailure(current => current ?? { message: error.message, problems: [], conflict: false });
    },
  });

  function edit(next: string) {
    setText(next);
    setNotice("");
  }
  function jumpToLine(line: number) {
    if (text === null || !editor.current) return;
    const range = lineRange(text, line);
    if (!range) return;
    editor.current.focus();
    editor.current.setSelectionRange(range.start, range.end);
    // Scroll roughly to the line: the textarea has no per-line API.
    const lineHeight = 20;
    editor.current.scrollTop = Math.max(0, (line - 4) * lineHeight);
  }
  async function importFile(file: File | undefined) {
    if (!file) return;
    if (file.size > MAX_WORKFLOW_YAML_BYTES) { setImportError("That file is larger than 64 KB."); return; }
    try {
      edit(await file.text());
      setImportError("");
      setFailure(null);
      setNotice(`Imported ${file.name}. Review it, then save.`);
    } catch {
      setImportError("Could not read that file.");
    }
    if (fileInput.current) fileInput.current.value = "";
  }

  if (session.isError || !session.data || isUnauthorizedError(workflow.error)) return <SessionFallback session={session} />;
  if (!isAdmin) return <AppShell session={session.data} active="workflow"><AdminOnly description="Only organization administrators can change document types, fields, rules and destinations." /></AppShell>;

  const saved = workflow.data;
  const summary = saved ? summarizeWorkflow(saved.config) : null;
  const dirty = saved !== undefined && text !== null && text !== saved.yaml;
  const scalars = text !== null ? workflowScalars(text) : null;
  const bytes = text !== null ? yamlByteLength(text) : 0;
  const lineCount = text !== null ? text.split("\n").length : 0;

  return <AppShell session={session.data} active="workflow">
    <SettingsHeader active="workflow" title="Workflow" description="The versioned configuration behind extraction and follow-up: document types and their fields, validation rules, review policy, and destinations. Every save creates a new version; nothing already extracted changes.">
      {saved && text !== null && <>
        <button type="button" className="secondary !min-h-10 text-sm" onClick={() => downloadText(workflowFilename(saved.version), text)}>Download YAML</button>
        <label className="secondary !min-h-10 cursor-pointer text-sm">Import YAML<input ref={fileInput} type="file" accept=".yaml,.yml,application/yaml,text/yaml,text/plain" className="sr-only" onChange={event => { void importFile(event.target.files?.[0]); }} /></label>
      </>}
    </SettingsHeader>

    {workflow.isPending && <p role="status" className="text-sm text-slate-500">Loading workflow…</p>}
    {workflow.isError && !isUnauthorizedError(workflow.error) && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{workflow.error.message} <button type="button" className="font-bold underline" onClick={() => workflow.refetch()}>Try again</button></p>}
    {notice && <p role="status" className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
    {importError && <p role="alert" className="mb-4 rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{importError}</p>}

    {saved && text !== null && scalars && <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <form className="min-w-0 space-y-4" onSubmit={event => { event.preventDefault(); if (dirty && !save.isPending) save.mutate(); }} aria-labelledby="editor-heading">
        <section className="card p-5">
          <h2 id="editor-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Review settings</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">These controls edit the YAML below in place; the YAML is what gets saved.</p>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="review-policy" className="mb-1 block text-xs font-semibold text-slate-700">Review policy</label>
              <select id="review-policy" className="field !py-2 text-sm" value={scalars.review_policy ?? ""} onChange={event => edit(setTopLevelScalar(text, "review_policy", event.target.value))}>
                {scalars.review_policy === null && <option value="">(not set)</option>}
                <option value="always">Always: every document is reviewed</option>
                <option value="threshold">Threshold: auto-approve when every field clears its confidence threshold</option>
              </select>
            </div>
            <div>
              <label htmlFor="review-sla" className="mb-1 block text-xs font-semibold text-slate-700">Review SLA (minutes)</label>
              <input id="review-sla" type="number" inputMode="numeric" min={SLA_MINUTES.min} max={SLA_MINUTES.max} className="field !py-2 text-sm" value={scalars.review_sla_minutes ?? ""} onChange={event => { if (/^\d+$/.test(event.target.value)) edit(setTopLevelScalar(text, "review_sla_minutes", Number(event.target.value))); }} />
              <p className="mt-1 text-[11px] text-slate-500">Due time for each review task; overdue reviews are flagged in the queue.</p>
            </div>
            <div>
              <label htmlFor="baseline-minutes" className="mb-1 block text-xs font-semibold text-slate-700">Manual baseline (minutes)</label>
              <input id="baseline-minutes" type="number" inputMode="numeric" min={BASELINE_MINUTES.min} max={BASELINE_MINUTES.max} className="field !py-2 text-sm" value={scalars.baseline_minutes ?? ""} onChange={event => { if (/^\d+$/.test(event.target.value)) edit(setTopLevelScalar(text, "baseline_minutes", Number(event.target.value))); }} />
              <p className="mt-1 text-[11px] text-slate-500">How long one document takes by hand; used for the time-saved figure in Insights.</p>
            </div>
          </div>
        </section>

        <section className="card p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <label htmlFor="workflow-yaml" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">YAML</label>
            <p className="text-xs text-slate-500">Editing version {saved.version} · {lineCount} lines · {(bytes / 1024).toFixed(1)} KB of 64{dirty && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-800">Unsaved</span>}</p>
          </div>
          <textarea id="workflow-yaml" ref={editor} className="field mt-3 min-h-[28rem] resize-y font-mono text-[12px] leading-5" spellCheck={false} autoCapitalize="off" autoCorrect="off" wrap="off" value={text} onChange={event => edit(event.target.value)} aria-invalid={failure && failure.problems.length > 0 ? true : undefined} aria-describedby={failure ? "workflow-problems" : undefined} />
          {failure && <div id="workflow-problems" role="alert" className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
            <p className="font-bold">{failure.message}</p>
            {failure.conflict && <p className="mt-1 text-xs">Someone saved a newer version. <button type="button" className="font-semibold underline" onClick={() => { if (workflow.data) { setText(workflow.data.yaml); setFailure(null); } }}>Load the latest version</button> (discards your edits) or download yours first and reapply them.</p>}
            {failure.problems.length > 0 && <ul className="mt-2 space-y-1 text-xs" data-testid="workflow-problem-list">
              {failure.problems.map((problem, index) => <li key={index} className="flex flex-wrap items-baseline gap-x-2">
                {problem.field && <code className="rounded bg-white/70 px-1 py-0.5 font-mono text-[11px]">{problem.field}</code>}
                <span>{problem.message}</span>
                {problem.line !== null && <button type="button" className="font-semibold underline" onClick={() => jumpToLine(problem.line!)}>Go to line {problem.line}</button>}
              </li>)}
            </ul>}
          </div>}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button type="submit" className="primary !min-h-10 text-sm" disabled={!dirty || save.isPending}>{save.isPending ? "Saving…" : `Save as version ${saved.version + 1}`}</button>
            <button type="button" className="secondary !min-h-10 text-sm" disabled={!dirty || save.isPending} onClick={() => { setText(saved.yaml); setFailure(null); setNotice(""); }}>Discard changes</button>
            <p className="text-xs text-slate-500">Validated by the API on save; every destination must name an existing connector of the right type.</p>
          </div>
        </section>
      </form>

      <aside className="min-w-0 space-y-4" aria-labelledby="summary-heading">
        <section className="card p-5">
          <h2 id="summary-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Saved configuration</h2>
          <p className="mt-1 text-xs text-slate-500">Version {saved.version} · saved {formatDateTime(saved.created_at)}. Reflects the last save, not unsaved edits.</p>
          {summary && <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
            <div className="rounded-xl bg-slate-50 p-3"><dt className="font-semibold text-slate-500">Review</dt><dd className="mt-1 font-bold capitalize text-slate-900">{summary.review_policy ?? "always"}</dd></div>
            <div className="rounded-xl bg-slate-50 p-3"><dt className="font-semibold text-slate-500">SLA</dt><dd className="mt-1 font-bold text-slate-900">{summary.review_sla_minutes ?? 240} min</dd></div>
            <div className="rounded-xl bg-slate-50 p-3"><dt className="font-semibold text-slate-500">Baseline</dt><dd className="mt-1 font-bold text-slate-900">{summary.baseline_minutes ?? 12} min</dd></div>
          </dl>}
        </section>

        {summary?.document_types.map(type => <section key={type.name} className="card p-5" aria-label={`Document type ${type.label ?? type.name}`}>
          <h3 className="text-sm font-bold text-slate-900">{type.label || type.name} <span className="ml-1 font-mono text-xs font-normal text-slate-500">{type.name}</span></h3>
          {type.detect && type.detect.length > 0 && <p className="mt-1 text-xs text-slate-500">Detected by: {type.detect.join(", ")}</p>}
          <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full min-w-[320px] text-left text-xs">
              <caption className="sr-only">Fields of {type.name}</caption>
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500"><tr><th scope="col" className="px-3 py-2 font-bold">Field</th><th scope="col" className="px-3 py-2 font-bold">Type</th><th scope="col" className="px-3 py-2 font-bold">Required</th><th scope="col" className="px-3 py-2 font-bold">Threshold</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {type.fields.map(field => <tr key={field.name}>
                  <th scope="row" className="px-3 py-2 font-semibold text-slate-800">{field.label || field.name}<span className="block font-mono text-[10px] font-normal text-slate-500">{field.name}</span></th>
                  <td className="px-3 py-2 text-slate-700">{field.type ?? "text"}</td>
                  <td className="px-3 py-2 text-slate-700">{field.required ? "Yes" : "No"}</td>
                  <td className="px-3 py-2 text-slate-700">{field.threshold !== undefined ? `${Math.round(field.threshold * 100)}%` : "80%"}</td>
                </tr>)}
              </tbody>
            </table>
          </div>
          {type.rules.length > 0 && <ul className="mt-3 space-y-1.5" aria-label={`Rules of ${type.name}`}>
            {type.rules.map(rule => <li key={rule.name} className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><span className="font-semibold text-slate-800">{rule.name}</span> <code className="ml-1 rounded bg-white px-1 py-0.5 font-mono text-[11px] text-slate-700">{rule.expression}</code>{rule.message && <span className="block text-slate-500">{rule.message}</span>}</li>)}
          </ul>}
        </section>)}

        <section className="card p-5" aria-labelledby="destinations-heading">
          <h3 id="destinations-heading" className="text-sm font-bold text-slate-900">Destinations</h3>
          {summary && summary.destinations.length === 0 && <p className="mt-1 text-xs leading-5 text-slate-500">None yet. Add a <code className="font-mono">destinations:</code> list naming a connector, an action type and a mapping of destination columns to document fields (or literals such as <code className="font-mono">{"${document.filename}"}</code>).</p>}
          {summary && summary.destinations.length > 0 && <ul className="mt-3 space-y-3">
            {summary.destinations.map(destination => <li key={destination.name} className="rounded-xl border border-slate-200 p-3 text-xs" data-destination={destination.name}>
              <div className="flex flex-wrap items-center gap-2"><span className="font-bold text-slate-900">{destination.name}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 capitalize text-slate-700">{actionTypeLabel(destination.action_type)}</span><span className="text-slate-500">via {destination.connector}</span>{!destination.enabled && <span className="rounded-full bg-amber-100 px-2 py-0.5 font-bold text-amber-800">Disabled</span>}</div>
              <p className="mt-1 text-slate-500">Applies to: {destination.document_types?.join(", ") ?? "every document type"}</p>
              <dl className="mt-2 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-3 gap-y-0.5">
                {Object.entries(destination.mapping).map(([column, source]) => <div key={column} className="contents"><dt className="truncate font-mono text-slate-700">{column}</dt><dd className="truncate font-mono text-slate-500">← {source}</dd></div>)}
              </dl>
            </li>)}
          </ul>}
          {summary && Object.keys(summary.action_policies).length > 0 && <p className="mt-3 text-xs text-slate-500">Default policies from this config: {Object.entries(summary.action_policies).map(([type, mode]) => `${actionTypeLabel(type)} → ${policyModeLabel(mode)}`).join(" · ")}</p>}
        </section>
      </aside>
    </div>}
  </AppShell>;
}
