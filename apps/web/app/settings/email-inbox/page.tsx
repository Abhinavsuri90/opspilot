"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { Switch } from "@/components/settings/Switch";
import { api } from "@/lib/api";
import { EMAIL_BACKENDS, backendDescriptions, backendLabels, emailInboxBody, emailInboxFormFromResponse, inboxHealth, parseEmailInboxForm, type EmailInboxFieldErrors, type EmailInboxFormValues, type EmailInboxResponse, type InboxHealth } from "@/lib/email-inbox";
import { apiErrorMessage, isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/use-workspace";

type TestResult = { ok: boolean; message: string; tested_at: string };

const healthCopy: Record<InboxHealth, { label: string; tone: string }> = {
  inactive: { label: "Paused", tone: "bg-slate-100 text-slate-600 ring-slate-200" },
  error: { label: "Last poll failed", tone: "bg-rose-50 text-rose-800 ring-rose-200" },
  healthy: { label: "Polling", tone: "bg-emerald-50 text-emerald-800 ring-emerald-200" },
  pending: { label: "Waiting for first poll", tone: "bg-amber-50 text-amber-800 ring-amber-200" },
};

function Field({ id, label, hint, error, children }: { id: string; label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return <div>
    <label htmlFor={id} className="mb-1 block text-xs font-semibold text-slate-700">{label}</label>
    {children}
    {hint && !error && <p className="mt-1 text-[11px] leading-4 text-slate-500">{hint}</p>}
    {error && <p id={`${id}-error`} role="alert" className="mt-1 text-xs font-semibold text-rose-700">{error}</p>}
  </div>;
}

function StatusPanel({ inbox, testing, testResult }: { inbox: EmailInboxResponse; testing: boolean; testResult: TestResult | undefined }) {
  const health = inboxHealth(inbox);
  const lastTest = testResult ?? (inbox.last_test_at ? { ok: Boolean(inbox.last_test_ok), message: inbox.last_test_message ?? "", tested_at: inbox.last_test_at } : undefined);
  const rows: { id: string; label: string; value: React.ReactNode }[] = [
    { id: "address", label: "Address", value: <span className="break-all font-mono">{inbox.address}</span> },
    { id: "backend", label: "Backend", value: backendLabels[inbox.backend === "mailpit" ? "mailpit" : "imap"] },
    { id: "last_polled", label: "Last polled", value: inbox.last_polled_at ? formatDateTime(inbox.last_polled_at) : "Not yet" },
    { id: "next_poll", label: "Next poll", value: inbox.active ? (inbox.next_poll_at ? formatDateTime(inbox.next_poll_at) : "Within a minute") : "Paused" },
    { id: "poll_interval", label: "Poll interval", value: `Every ${inbox.poll_interval_seconds} s` },
    { id: "messages_processed", label: "Messages processed", value: inbox.messages_processed.toLocaleString("en-US") },
    { id: "documents_created", label: "Documents created", value: inbox.documents_created.toLocaleString("en-US") },
    { id: "credentials", label: "Credentials", value: inbox.has_credentials ? "Stored (encrypted)" : "None stored" },
  ];
  return <section aria-labelledby="inbox-status-heading" className="card min-w-0 self-start p-5" data-testid="inbox-status">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="inbox-status-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Status</h2>
      <span data-testid="inbox-health" className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ring-1 ${healthCopy[health].tone}`}>{healthCopy[health].label}</span>
    </div>
    <dl className="mt-3 grid gap-x-4 gap-y-2 text-xs sm:grid-cols-2">
      {rows.map(row => <div key={row.id}><dt className="font-semibold text-slate-500">{row.label}</dt><dd className="mt-0.5 text-slate-800" data-testid={`inbox-stat-${row.id}`}>{row.value}</dd></div>)}
    </dl>
    {inbox.last_error && <p role="alert" className="mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-800"><span className="font-bold">Last error:</span> {inbox.last_error}</p>}
    <p className="mt-3 text-xs" data-testid="inbox-last-test">
      {testing ? <span className="text-slate-500">Testing…</span> : lastTest
        ? <><span className={`font-bold ${lastTest.ok ? "text-emerald-700" : "text-rose-700"}`}>{lastTest.ok ? "Test passed" : "Test failed"}</span><span className="text-slate-600"> · {lastTest.message} · {formatDateTime(lastTest.tested_at)}</span></>
        : <span className="text-slate-500">Connection not tested yet.</span>}
    </p>
  </section>;
}

export default function EmailInboxSettingsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const session = useWorkspace();
  const isAdmin = session.data?.role === "admin";
  const slug = session.data?.org_slug ?? "";
  const key = ["email-inbox", session.data?.org_id, session.data?.user_id];
  const inbox = useQuery({
    queryKey: key,
    enabled: isAdmin,
    queryFn: async () => {
      const result = await api.GET("/v1/settings/email-inbox");
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error) throw new Error("Could not load the email inbox settings.");
      return result.data ?? null;
    },
    refetchInterval: 15_000,
  });
  const [values, setValues] = useState<EmailInboxFormValues>(() => emailInboxFormFromResponse(null));
  const [dirty, setDirty] = useState(false);
  const [errors, setErrors] = useState<EmailInboxFieldErrors>({});
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestResult | undefined>();

  // A poll or another administrator's save refreshes an untouched form; unsaved edits are kept.
  useEffect(() => {
    if (inbox.data === undefined || dirty) return;
    setValues(emailInboxFormFromResponse(inbox.data));
  }, [inbox.data, dirty]);
  useEffect(() => {
    if (isUnauthorizedError(inbox.error)) { client.clear(); router.replace("/login"); }
  }, [inbox.error, client, router]);

  const save = useMutation({
    mutationFn: async (form: EmailInboxFormValues) => {
      const parsed = parseEmailInboxForm(form, { hasCredentials: Boolean(inbox.data?.has_credentials) });
      if (!parsed.ok) { setErrors(parsed.errors); throw new Error("Fix the highlighted fields."); }
      setErrors({});
      const result = await api.POST("/v1/settings/email-inbox", { body: emailInboxBody(parsed.value, inbox.data?.version ?? 0) });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) {
        const status = result.response.status;
        if (status === 409) await inbox.refetch();
        throw new Error(apiErrorMessage(result.error, status, status === 409 ? "The inbox changed since you loaded it. The settings have been refreshed; review and save again." : "Could not save the inbox."));
      }
      return result.data;
    },
    onSuccess: saved => {
      client.setQueryData(key, saved);
      setValues(emailInboxFormFromResponse(saved));
      setDirty(false);
      setFailure(null);
      setNotice(saved.active ? `Inbox saved as version ${saved.version}. The worker polls ${saved.address} every ${saved.poll_interval_seconds} seconds.` : `Inbox saved as version ${saved.version}. Polling is paused until you activate it.`);
    },
    onError: error => {
      if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); return; }
      setNotice("");
      setFailure(error.message);
    },
  });

  const test = useMutation({
    mutationFn: async () => {
      const result = await api.POST("/v1/settings/email-inbox/test");
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, "The connection test could not run."));
      return result.data;
    },
    onSuccess: async outcome => {
      setTestResult(outcome);
      setFailure(null);
      await client.invalidateQueries({ queryKey: ["email-inbox"] });
    },
    onError: error => {
      if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); return; }
      setFailure(error.message);
    },
  });

  function update(patch: Partial<EmailInboxFormValues>) {
    setValues(current => ({ ...current, ...patch }));
    setDirty(true);
    setErrors({});
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (save.isPending) return;
    setNotice("");
    save.mutate(values);
  }

  if (session.isError || !session.data || isUnauthorizedError(inbox.error)) return <SessionFallback session={session} />;
  if (!isAdmin) return <AppShell session={session.data} active="email-inbox"><AdminOnly description="Only organization administrators can connect a mailbox or change how it is polled." /></AppShell>;

  const stored = inbox.data ?? null;
  const input = (field: keyof EmailInboxFormValues, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => <input id={`inbox-${field}`} className="field !py-2 text-sm" value={String(values[field])} onChange={event => update({ [field]: event.target.value })} disabled={save.isPending} aria-invalid={errors[field] ? true : undefined} aria-describedby={errors[field] ? `inbox-${field}-error` : undefined} {...extra} />;
  const mailpitAddress = stored?.backend === "mailpit" ? stored.address : `${slug || "<workspace-id>"}@opspilot.local`;

  return <AppShell session={session.data} active="email-inbox">
    <SettingsHeader active="email-inbox" title="Email inbox" description="Let vendors email documents straight into the workspace. The worker polls the mailbox, turns every PDF attachment into a document and keeps the message body beside it for the reviewer." />

    {notice && <p role="status" className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
    {failure && <p role="alert" className="mb-4 rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{failure}</p>}
    {inbox.isPending && <p role="status" className="text-sm text-slate-500">Loading inbox settings…</p>}
    {inbox.isError && !isUnauthorizedError(inbox.error) && <p role="alert" className="mb-4 rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{inbox.error.message} <button type="button" className="font-bold underline" onClick={() => inbox.refetch()}>Try again</button></p>}

    {inbox.isSuccess && <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <form onSubmit={submit} className="card min-w-0 p-5" aria-labelledby="inbox-form-heading">
        <h2 id="inbox-form-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">{stored ? "Mailbox" : "Connect a mailbox"}</h2>
        <fieldset className="mt-4">
          <legend className="mb-2 text-xs font-semibold text-slate-700">Backend</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {EMAIL_BACKENDS.map(backend => <label key={backend} className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-sm ${values.backend === backend ? "border-[#11627a] bg-cyan-50/60 ring-1 ring-[#11627a]" : "border-slate-200 hover:bg-slate-50"}`}>
              <input type="radio" name="inbox-backend" value={backend} checked={values.backend === backend} onChange={() => update({ backend })} disabled={save.isPending} className="mt-1" />
              <span><span className="block font-bold text-slate-900">{backendLabels[backend]}</span><span className="mt-0.5 block text-xs leading-5 text-slate-600">{backendDescriptions[backend]}</span></span>
            </label>)}
          </div>
        </fieldset>

        {values.backend === "imap" && <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2"><Field id="inbox-address" label="Mailbox address" hint="The address vendors send documents to; it appears on each document as its source." error={errors.address}>{input("address", { inputMode: "email", autoComplete: "off", placeholder: "ap@example.com" })}</Field></div>
          <Field id="inbox-host" label="IMAP host" hint="TLS on the given port (993 by default)." error={errors.host}>{input("host", { autoComplete: "off", placeholder: "imap.example.com" })}</Field>
          <Field id="inbox-port" label="Port" error={errors.port}>{input("port", { inputMode: "numeric", autoComplete: "off" })}</Field>
          <Field id="inbox-username" label="User name" error={errors.username}>{input("username", { autoComplete: "off", placeholder: "ap@example.com" })}</Field>
          <Field id="inbox-folder" label="Folder" hint="Usually INBOX. Unread messages are fetched and marked as read." error={errors.folder}>{input("folder", { autoComplete: "off" })}</Field>
          <div className="sm:col-span-2"><Field id="inbox-password" label={stored?.has_credentials ? "New password" : "Password"} hint={stored?.has_credentials ? "Leave blank to keep the stored password. Stored encrypted; never shown again." : "Stored encrypted; never shown again."} error={errors.password}>{input("password", { type: "password", autoComplete: "new-password" })}</Field></div>
        </div>}
        {values.backend === "mailpit" && <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/60 p-4 text-sm text-slate-700">
          <p>Messages sent to <span data-testid="mailpit-address" className="break-all font-mono font-semibold text-slate-900">{mailpitAddress}</span> on the local Mailpit server are picked up. Nothing else to configure; the API rejects this backend outside development.</p>
        </div>}

        <div className="mt-5 rounded-xl border border-slate-200 p-4">
          <Switch label="Polling active" checked={values.active} disabled={save.isPending} description="When off, the mailbox is kept but not polled. Turn it off to pause intake without losing the configuration." onChange={active => update({ active })} badge={values.active ? <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-emerald-800 ring-1 ring-emerald-200">On</span> : <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-slate-600">Off</span>} />
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button type="submit" className="primary !min-h-10 text-sm" disabled={save.isPending}>{save.isPending ? "Saving…" : stored ? `Save as version ${stored.version + 1}` : "Save inbox"}</button>
          {stored && <button type="button" className="secondary !min-h-10 text-sm" disabled={save.isPending || test.isPending} onClick={() => { setNotice(""); test.mutate(); }}>{test.isPending ? "Testing…" : "Test connection"}</button>}
          {dirty && <button type="button" className="secondary !min-h-10 text-sm" disabled={save.isPending} onClick={() => { setValues(emailInboxFormFromResponse(stored)); setDirty(false); setErrors({}); }}>Discard changes</button>}
          {stored && <span className="text-xs text-slate-500">Version {stored.version} · saved {formatDateTime(stored.updated_at)}{dirty && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-800">Unsaved</span>}</span>}
        </div>
        {!stored && <p className="mt-3 text-xs text-slate-500">Save first, then test the connection. The first poll happens within a minute of saving an active inbox.</p>}
      </form>

      {stored ? <StatusPanel inbox={stored} testing={test.isPending} testResult={testResult} /> : <section aria-labelledby="inbox-status-heading" className="card self-start p-5"><h2 id="inbox-status-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Status</h2><p className="mt-2 text-sm leading-6 text-slate-600">No mailbox is connected yet. Once one is saved this panel shows when it was last polled, the next poll, the last error, and how many messages and documents it produced.</p></section>}
    </div>}
  </AppShell>;
}
