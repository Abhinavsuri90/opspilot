"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { Dialog } from "@/components/review/Dialog";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { api } from "@/lib/api";
import { apiKeyNameSchema, apiKeyState, curlExample, lastUsedLabel, maskedKey, sortApiKeys, type ApiKeyCreatedResponse, type ApiKeyResponse } from "@/lib/api-keys";
import { apiErrorMessage, isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/use-workspace";

/** The one moment the secret is visible: a copy box that the administrator dismisses once it is saved elsewhere. */
function FreshKeyPanel({ created, onDismiss }: { created: ApiKeyCreatedResponse; onDismiss: () => void }) {
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (copied === "idle") return;
    const timer = setTimeout(() => setCopied("idle"), 2500);
    return () => clearTimeout(timer);
  }, [copied]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied("copied");
    } catch {
      setCopied("failed");
    }
  }
  return <section aria-labelledby="fresh-key-heading" data-testid="fresh-key" className="card mb-5 border-2 !border-emerald-300 p-5">
    <h2 id="fresh-key-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Key “{created.name}” created</h2>
    <p className="mt-1 text-sm leading-6 text-slate-600">Copy it now and store it in your integration&apos;s secret store. <strong>It is shown only once</strong>; OpsPilot keeps a hash and cannot display it again.</p>
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <code data-testid="fresh-key-value" className="min-w-0 flex-1 select-all break-all rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-slate-900">{created.key}</code>
      <button type="button" className="secondary !min-h-10 text-sm" onClick={copy} aria-live="polite">{copied === "copied" ? "Copied" : copied === "failed" ? "Select and copy manually" : "Copy key"}</button>
    </div>
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button type="button" className="primary !min-h-10 text-sm" onClick={onDismiss}>I have saved it</button>
      <span className="text-xs text-slate-500">Prefix <span className="font-mono">{created.key_prefix}</span> identifies this key in the audit log.</span>
    </div>
  </section>;
}

export default function ApiKeysSettingsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const session = useWorkspace();
  const isAdmin = session.data?.role === "admin";
  const key = ["api-keys", session.data?.org_id, session.data?.user_id];
  const keys = useQuery({
    queryKey: key,
    enabled: isAdmin,
    queryFn: async () => {
      const result = await api.GET("/v1/settings/api-keys");
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load API keys.");
      return result.data;
    },
    refetchInterval: 30_000,
  });
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState("");
  const [fresh, setFresh] = useState<ApiKeyCreatedResponse | null>(null);
  const [revoking, setRevoking] = useState<ApiKeyResponse | null>(null);
  const [notice, setNotice] = useState("");
  const [origin, setOrigin] = useState("https://your-opspilot-host");
  useEffect(() => { setOrigin(window.location.origin); }, []);
  useEffect(() => {
    if (isUnauthorizedError(keys.error)) { client.clear(); router.replace("/login"); }
  }, [keys.error, client, router]);

  const create = useMutation({
    mutationFn: async (value: string) => {
      const result = await api.POST("/v1/settings/api-keys", { body: { name: value } });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, "Could not create the key."));
      return result.data;
    },
    onSuccess: async created => {
      setFresh(created);
      setName("");
      setNotice("");
      await client.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: error => { if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); } },
  });

  const revoke = useMutation({
    mutationFn: async (target: ApiKeyResponse) => {
      const result = await api.POST("/v1/settings/api-keys/{key_id}/revoke", { params: { path: { key_id: target.id } } });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, "Could not revoke the key."));
      return result.data;
    },
    onSuccess: async revoked => {
      setRevoking(null);
      setNotice(`Key “${revoked.name}” revoked. Requests with it are rejected from now on.`);
      if (fresh?.id === revoked.id) setFresh(null);
      await client.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: error => { if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); } },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (create.isPending) return;
    const parsed = apiKeyNameSchema.safeParse(name);
    if (!parsed.success) { setNameError(parsed.error.issues[0]?.message ?? "Enter a name."); return; }
    setNameError("");
    create.reset();
    create.mutate(parsed.data);
  }

  if (session.isError || !session.data || isUnauthorizedError(keys.error)) return <SessionFallback session={session} />;
  if (!isAdmin) return <AppShell session={session.data} active="api-keys"><AdminOnly description="Only organization administrators can create or revoke API keys." /></AppShell>;

  const list = sortApiKeys(keys.data ?? []);
  const examplePrefix = fresh?.key_prefix ?? list.find(item => !item.revoked_at)?.key_prefix ?? "";

  return <AppShell session={session.data} active="api-keys">
    <SettingsHeader active="api-keys" title="API keys" description="Let another system send documents straight into this workspace. Each key uploads on behalf of the administrator who created it, is limited to 60 uploads per 15 minutes, and can be revoked at any time." />

    {notice && <p role="status" className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
    {fresh && <FreshKeyPanel created={fresh} onDismiss={() => setFresh(null)} />}

    <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <form onSubmit={submit} className="card min-w-0 self-start p-5" aria-labelledby="new-key-heading">
        <h2 id="new-key-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">New key</h2>
        <p className="mt-1 text-xs leading-5 text-slate-500">Name it after the system that will use it, so the audit log and the source badge on each document make sense later.</p>
        <label htmlFor="api-key-name" className="mt-4 block text-xs font-semibold text-slate-700">Key name</label>
        <input id="api-key-name" className="field mt-1 !py-2 text-sm" value={name} onChange={event => { setName(event.target.value); setNameError(""); }} maxLength={100} placeholder="Warehouse scanner" disabled={create.isPending} aria-invalid={nameError ? true : undefined} aria-describedby={nameError ? "api-key-name-error" : undefined} />
        {nameError && <p id="api-key-name-error" role="alert" className="mt-1 text-xs font-semibold text-rose-700">{nameError}</p>}
        {create.error && !isUnauthorizedError(create.error) && <p role="alert" className="mt-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{create.error.message}</p>}
        <button type="submit" className="primary mt-4 !min-h-10 text-sm" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create key"}</button>
      </form>

      <section aria-labelledby="usage-heading" className="card min-w-0 self-start p-5">
        <h2 id="usage-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Using a key</h2>
        <p className="mt-1 text-xs leading-5 text-slate-500">Send the key as a Bearer token on <code className="font-mono">POST /api/v1/documents</code> with the PDF as the <code className="font-mono">file</code> form field. The response is the same document summary the inbox shows; poll <code className="font-mono">GET /api/v1/documents/&#123;id&#125;</code> for its status. Uploads carry an <em>API</em> source badge in the inbox.</p>
        <pre data-testid="curl-example" className="mt-3 overflow-x-auto rounded-xl bg-[#0d2039] p-4 font-mono text-xs leading-6 text-cyan-100"><code>{curlExample(origin, examplePrefix)}</code></pre>
        <p className="mt-2 text-xs text-slate-500">Replace <code className="font-mono">&lt;secret&gt;</code> with the part of your key after its prefix. Keys only have the <code className="font-mono">documents:write</code> scope.</p>
      </section>
    </div>

    <section aria-labelledby="keys-heading" className="card mt-5 overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-5"><h2 id="keys-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Keys</h2><p className="mt-1 text-xs leading-5 text-slate-500">Only the prefix is kept in clear text. Revoking is immediate and cannot be undone; create a new key to rotate.</p></div>
      {keys.isPending && <p role="status" className="px-6 py-10 text-center text-sm text-slate-500">Loading keys…</p>}
      {keys.isError && !isUnauthorizedError(keys.error) && <p role="alert" className="px-6 py-8 text-sm text-rose-800">{keys.error.message} <button type="button" className="font-semibold underline" onClick={() => keys.refetch()}>Try again</button></p>}
      {keys.isSuccess && list.length === 0 && <p className="px-6 py-10 text-center text-sm text-slate-500">No keys yet. Create one to let another system upload documents.</p>}
      {list.length > 0 && <ul className="divide-y divide-slate-100" aria-label="API keys">
        {list.map(item => {
          const state = apiKeyState(item);
          return <li key={item.id} data-testid="api-key-row" data-key-state={state} className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="break-words text-sm font-bold text-slate-900">{item.name}</h3>
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ring-1 ${state === "active" ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-200"}`}>{state === "active" ? "Active" : "Revoked"}</span>
              </div>
              <p className="mt-1 font-mono text-xs text-slate-600">{maskedKey(item.key_prefix)}</p>
              <p className="mt-1 text-xs text-slate-500">Created {formatDateTime(item.created_at)}{item.created_by_email && <> by <span className="break-all">{item.created_by_email}</span></>} · {lastUsedLabel(item.last_used_at, formatDateTime)}{item.revoked_at && ` · revoked ${formatDateTime(item.revoked_at)}`}</p>
            </div>
            {state === "active" && <button type="button" className="secondary !min-h-9 !px-3 !text-xs !text-rose-700" disabled={revoke.isPending} onClick={() => { setNotice(""); revoke.reset(); setRevoking(item); }}>Revoke</button>}
          </li>;
        })}
      </ul>}
    </section>

    {revoking && <Dialog title={`Revoke key “${revoking.name}”?`} description="Every request that uses this key is rejected immediately. The systems that hold it will need a new key." onClose={() => { if (!revoke.isPending) setRevoking(null); }} testId="revoke-key-dialog">
      {revoke.error && !isUnauthorizedError(revoke.error) && <p role="alert" className="mb-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{revoke.error.message}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" className="secondary text-sm" onClick={() => setRevoking(null)} disabled={revoke.isPending}>Cancel</button>
        <button type="button" className="rounded-lg bg-rose-700 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-800 disabled:opacity-50" onClick={() => revoke.mutate(revoking)} disabled={revoke.isPending}>{revoke.isPending ? "Revoking…" : "Revoke key"}</button>
      </div>
    </Dialog>}
  </AppShell>;
}
