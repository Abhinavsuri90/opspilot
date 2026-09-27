"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { actionTypeLabel } from "@/lib/actions";
import { api } from "@/lib/api";
import { CONNECTOR_TYPES, connectorActionTypes, connectorCreateBody, connectorFormFromResponse, connectorTakesCredentials, connectorTypeDescriptions, connectorTypeLabels, connectorUpdateBody, emptyConnectorForm, isConnectorType, parseConnectorForm, type ConnectorFieldErrors, type ConnectorFormValues, type ConnectorResponse, type ConnectorType, type ConnectorUpdate } from "@/lib/connectors";
import { apiErrorMessage, isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { exportFileUrl } from "@/lib/urls";
import { useWorkspace } from "@/lib/use-workspace";

type TestResult = { ok: boolean; message: string; tested_at: string };

function Field({ id, label, hint, error, children }: { id: string; label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return <div>
    <label htmlFor={id} className="mb-1 block text-xs font-semibold text-slate-700">{label}</label>
    {children}
    {hint && !error && <p className="mt-1 text-[11px] leading-4 text-slate-500">{hint}</p>}
    {error && <p id={`${id}-error`} role="alert" className="mt-1 text-xs font-semibold text-rose-700">{error}</p>}
  </div>;
}

type ConnectorFormProps = {
  idPrefix: string;
  type: ConnectorType;
  mode: "create" | "edit";
  values: ConnectorFormValues;
  errors: ConnectorFieldErrors;
  disabled: boolean;
  hasCredentials?: boolean;
  onChange: (values: ConnectorFormValues) => void;
};

/** The fields one connector type needs; credentials are write-only and never prefilled. */
function ConnectorFields({ idPrefix, type, mode, values, errors, disabled, hasCredentials = false, onChange }: ConnectorFormProps) {
  const set = (key: keyof ConnectorFormValues) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange({ ...values, [key]: event.target.value });
  const input = (key: keyof ConnectorFormValues, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => <input id={`${idPrefix}-${key}`} className="field !py-2 text-sm" value={values[key]} onChange={set(key)} disabled={disabled} aria-invalid={errors[key] ? true : undefined} aria-describedby={errors[key] ? `${idPrefix}-${key}-error` : undefined} {...extra} />;
  const credentialHint = mode === "edit" ? (hasCredentials ? "Leave blank to keep the stored value." : "No credentials are stored yet.") : undefined;
  return <div className="grid gap-4 sm:grid-cols-2">
    <Field id={`${idPrefix}-name`} label="Name" hint="Referenced by destinations in the workflow configuration." error={errors.name}>{input("name", { maxLength: 100, placeholder: "Accounting webhook" })}</Field>
    {type === "webhook" && <>
      <Field id={`${idPrefix}-url`} label="Endpoint URL" hint="https:// in production; plain http:// only works in development." error={errors.url}>{input("url", { inputMode: "url", placeholder: "https://hooks.example.com/opspilot" })}</Field>
      <Field id={`${idPrefix}-secret`} label={mode === "edit" ? "New signing secret" : "Signing secret"} hint={credentialHint ?? "At least 16 characters. Used to sign every request; never shown again."} error={errors.secret}>{input("secret", { type: "password", autoComplete: "new-password" })}</Field>
      <Field id={`${idPrefix}-headers`} label="Static headers" hint="One per line as Name: value, for example X-Tenant: acme." error={errors.headers}><textarea id={`${idPrefix}-headers`} className="field !py-2 font-mono text-xs" rows={3} value={values.headers} onChange={set("headers")} disabled={disabled} spellCheck={false} /></Field>
    </>}
    {type === "csv_export" && <Field id={`${idPrefix}-file_prefix`} label="File prefix" hint="Files are named prefix-YYYY-MM.csv. Defaults to export." error={errors.file_prefix}>{input("file_prefix", { placeholder: "export" })}</Field>}
    {type === "postgres_table" && <>
      <Field id={`${idPrefix}-schema`} label="Schema" error={errors.schema}>{input("schema", { placeholder: "public" })}</Field>
      <Field id={`${idPrefix}-table`} label="Table" hint="Must have a text column opspilot_action_id; rows are keyed by it so retries never duplicate." error={errors.table}>{input("table", { placeholder: "ap_invoices" })}</Field>
      <Field id={`${idPrefix}-dsn`} label={mode === "edit" ? "New connection string" : "Connection string"} hint={credentialHint ?? "postgresql://user:password@host:5432/database. Stored encrypted; never shown again."} error={errors.dsn}>{input("dsn", { type: "password", autoComplete: "off" })}</Field>
    </>}
    {type === "google_sheets" && <>
      <Field id={`${idPrefix}-spreadsheet_id`} label="Spreadsheet id" hint="The long id in the spreadsheet URL." error={errors.spreadsheet_id}>{input("spreadsheet_id")}</Field>
      <Field id={`${idPrefix}-sheet_name`} label="Sheet (tab) name" error={errors.sheet_name}>{input("sheet_name", { placeholder: "Invoices" })}</Field>
      <div className="sm:col-span-2"><Field id={`${idPrefix}-service_account_json`} label={mode === "edit" ? "New service account JSON" : "Service account JSON"} hint={credentialHint ?? "Paste the key file. Share the spreadsheet with its client_email. Stored encrypted; never shown again."} error={errors.service_account_json}><textarea id={`${idPrefix}-service_account_json`} className="field !py-2 font-mono text-xs" rows={5} value={values.service_account_json} onChange={set("service_account_json")} disabled={disabled} spellCheck={false} autoComplete="off" /></Field></div>
    </>}
  </div>;
}

function ExportsList({ connector }: { connector: ConnectorResponse }) {
  const exports = useQuery({
    queryKey: ["exports", connector.id],
    queryFn: async () => {
      const result = await api.GET("/v1/exports", { params: { query: { connector_id: connector.id } } });
      if (result.error || !result.data) throw new Error("Could not list exports.");
      return result.data;
    },
    refetchInterval: 30_000,
  });
  return <li className="px-5 py-4" data-testid={`exports-${connector.id}`}>
    <p className="text-sm font-bold text-slate-900">{connector.name}<span className="ml-2 font-normal text-slate-500">prefix {String(connector.config.file_prefix ?? "export")}</span></p>
    {exports.isPending && <p role="status" className="mt-1 text-xs text-slate-500">Loading months…</p>}
    {exports.isError && <p role="alert" className="mt-1 text-xs text-rose-700">{exports.error.message}</p>}
    {exports.data && exports.data.length === 0 && <p className="mt-1 text-xs text-slate-500">No rows exported yet. The first executed export_csv action creates this month&apos;s file.</p>}
    {exports.data && exports.data.length > 0 && <ul className="mt-2 flex flex-wrap gap-2">
      {exports.data.map(month => <li key={month.month}><a href={exportFileUrl(month.connector_id, month.month)} className="secondary !min-h-8 !px-3 !text-xs" download>{month.month}.csv ↓</a></li>)}
    </ul>}
  </li>;
}

type RowProps = {
  connector: ConnectorResponse;
  saving: boolean;
  testing: boolean;
  testResult: TestResult | undefined;
  error: string | null;
  onSave: (connector: ConnectorResponse, values: ConnectorFormValues) => ConnectorFieldErrors | null;
  onToggleActive: (connector: ConnectorResponse) => void;
  onTest: (connector: ConnectorResponse) => void;
};

function ConnectorRow({ connector, saving, testing, testResult, error, onSave, onToggleActive, onTest }: RowProps) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<ConnectorFormValues>(() => connectorFormFromResponse(connector));
  const [errors, setErrors] = useState<ConnectorFieldErrors>({});
  useEffect(() => { setValues(connectorFormFromResponse(connector)); setErrors({}); setEditing(false); }, [connector]);
  const type = isConnectorType(connector.connector_type) ? connector.connector_type : null;
  const lastTest = testResult ?? (connector.last_test_at ? { ok: Boolean(connector.last_test_ok), message: connector.last_test_message ?? "", tested_at: connector.last_test_at } : undefined);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problems = onSave(connector, values);
    setErrors(problems ?? {});
  }

  return <li className="px-5 py-5" data-connector-name={connector.name} data-testid="connector-row">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="break-words text-sm font-bold text-slate-900">{connector.name}</h3>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-600">{type ? connectorTypeLabels[type] : connector.connector_type}</span>
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ring-1 ${connector.active ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-200"}`}>{connector.active ? "Active" : "Inactive"}</span>
          {type && connectorTakesCredentials(type) && <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${connector.has_credentials ? "bg-cyan-50 text-cyan-800 ring-cyan-200" : "bg-amber-50 text-amber-800 ring-amber-200"}`}>{connector.has_credentials ? "Credentials stored" : "No credentials"}</span>}
        </div>
        <p className="mt-1 break-all text-xs text-slate-500">
          {type === "webhook" && String(connector.config.url ?? "")}
          {type === "csv_export" && `prefix ${String(connector.config.file_prefix ?? "export")}`}
          {type === "postgres_table" && `${String(connector.config.schema ?? "")}.${String(connector.config.table ?? "")}`}
          {type === "google_sheets" && `${String(connector.config.spreadsheet_id ?? "")} · ${String(connector.config.sheet_name ?? "")}`}
          {type && <> · executes <span className="capitalize">{actionTypeLabel(connectorActionTypes[type])}</span></>}
        </p>
        <p className="mt-1 text-xs" data-testid="last-test">
          {testing ? <span className="text-slate-500">Testing…</span> : lastTest
            ? <><span className={`font-bold ${lastTest.ok ? "text-emerald-700" : "text-rose-700"}`}>{lastTest.ok ? "Test passed" : "Test failed"}</span><span className="text-slate-600"> · {lastTest.message} · {formatDateTime(lastTest.tested_at)}</span></>
            : <span className="text-slate-500">Not tested yet.</span>}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="secondary !min-h-9 !px-3 !text-xs" disabled={saving || testing} onClick={() => onTest(connector)}>Test connection</button>
        <button type="button" className="secondary !min-h-9 !px-3 !text-xs" disabled={saving} onClick={() => setEditing(open => !open)} aria-expanded={editing}>{editing ? "Close" : "Edit"}</button>
        <button type="button" className="min-h-9 rounded-lg px-3 text-xs font-semibold text-slate-600 hover:bg-slate-100" disabled={saving} onClick={() => onToggleActive(connector)}>{connector.active ? "Deactivate" : "Reactivate"}</button>
      </div>
    </div>
    {error && <p role="alert" className="mt-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    {editing && type && <form onSubmit={submit} className="mt-4 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
      <ConnectorFields idPrefix={`edit-${connector.id}`} type={type} mode="edit" values={values} errors={errors} disabled={saving} hasCredentials={connector.has_credentials} onChange={setValues} />
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="submit" className="primary !min-h-10 text-sm" disabled={saving}>{saving ? "Saving…" : "Save connector"}</button>
        <button type="button" className="secondary !min-h-10 text-sm" disabled={saving} onClick={() => { setValues(connectorFormFromResponse(connector)); setErrors({}); setEditing(false); }}>Cancel</button>
      </div>
    </form>}
  </li>;
}

export default function ConnectorsSettingsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const session = useWorkspace();
  const isAdmin = session.data?.role === "admin";
  const key = ["connectors", session.data?.org_id, session.data?.user_id];
  const connectors = useQuery({
    queryKey: key,
    enabled: isAdmin,
    queryFn: async () => {
      const result = await api.GET("/v1/settings/connectors");
      if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
      if (result.error || !result.data) throw new Error("Could not load connectors.");
      return result.data;
    },
    refetchInterval: 30_000,
  });
  const [creating, setCreating] = useState(false);
  const [createType, setCreateType] = useState<ConnectorType>("webhook");
  const [createValues, setCreateValues] = useState<ConnectorFormValues>(emptyConnectorForm);
  const [createErrors, setCreateErrors] = useState<ConnectorFieldErrors>({});
  const [notice, setNotice] = useState("");
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  useEffect(() => {
    if (isUnauthorizedError(connectors.error)) { client.clear(); router.replace("/login"); }
  }, [connectors.error, client, router]);

  const failure = (error: unknown, status: number, fallback: string) => apiErrorMessage(error, status, status === 409 ? "This connector changed since you loaded it (or the name is taken). The list has been refreshed." : fallback);

  const create = useMutation({
    mutationFn: async () => {
      const parsed = parseConnectorForm(createType, "create", createValues);
      if (!parsed.ok) { setCreateErrors(parsed.errors); throw new Error("Fix the highlighted fields."); }
      setCreateErrors({});
      const result = await api.POST("/v1/settings/connectors", { body: connectorCreateBody(createType, parsed.value) });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) throw new Error(failure(result.error, result.response.status, "Could not create the connector."));
      return result.data;
    },
    onSuccess: async created => {
      setNotice(`Connector “${created.name}” created. Test the connection, then reference it from a destination in the workflow.`);
      setCreating(false);
      setCreateValues(emptyConnectorForm);
      await client.invalidateQueries({ queryKey: ["connectors"] });
    },
    onError: error => { if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); } },
  });

  const update = useMutation({
    mutationFn: async ({ connector, body }: { connector: ConnectorResponse; body: ConnectorUpdate }) => {
      const result = await api.POST("/v1/settings/connectors/{connector_id}", { params: { path: { connector_id: connector.id } }, body });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) {
        if (result.response.status === 409) await client.invalidateQueries({ queryKey: ["connectors"] });
        throw new Error(failure(result.error, result.response.status, "Could not update the connector."));
      }
      return result.data;
    },
    onSuccess: async (saved, input) => {
      setRowErrors(current => { const next = { ...current }; delete next[input.connector.id]; return next; });
      setNotice(input.body.active === false ? `Connector “${saved.name}” deactivated. Actions that need it fail until it is reactivated.` : input.body.active === true ? `Connector “${saved.name}” reactivated.` : `Connector “${saved.name}” saved.`);
      await client.invalidateQueries({ queryKey: ["connectors"] });
    },
    onError: (error, input) => {
      if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); return; }
      setNotice("");
      setRowErrors(current => ({ ...current, [input.connector.id]: error.message }));
    },
  });

  const test = useMutation({
    mutationFn: async (connector: ConnectorResponse) => {
      const result = await api.POST("/v1/settings/connectors/{connector_id}/test", { params: { path: { connector_id: connector.id } } });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, "The connection test could not run."));
      return result.data;
    },
    onSuccess: async (outcome, connector) => {
      setTestResults(current => ({ ...current, [connector.id]: outcome }));
      setRowErrors(current => { const next = { ...current }; delete next[connector.id]; return next; });
      await client.invalidateQueries({ queryKey: ["connectors"] });
    },
    onError: (error, connector) => {
      if (isUnauthorizedError(error)) { client.clear(); router.replace("/login"); return; }
      setRowErrors(current => ({ ...current, [connector.id]: error.message }));
    },
  });

  if (session.isError || !session.data || isUnauthorizedError(connectors.error)) return <SessionFallback session={session} />;
  if (!isAdmin) return <AppShell session={session.data} active="connectors"><AdminOnly description="Only organization administrators can add destinations, rotate their credentials or run connection tests." /></AppShell>;

  const list = [...(connectors.data ?? [])].sort((a, b) => Number(b.active) - Number(a.active) || a.name.localeCompare(b.name));
  const csvConnectors = list.filter(connector => connector.connector_type === "csv_export");

  return <AppShell session={session.data} active="connectors">
    <SettingsHeader active="connectors" title="Connectors" description="Where approved data goes. Each connector holds one destination's address and encrypted credentials; workflow destinations reference connectors by name.">
      <button type="button" className="primary !min-h-10 text-sm" onClick={() => { setCreating(open => !open); setNotice(""); }} aria-expanded={creating}>{creating ? "Close form" : "New connector"}</button>
    </SettingsHeader>

    {notice && <p role="status" className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}

    {creating && <form onSubmit={event => { event.preventDefault(); if (!create.isPending) { setNotice(""); create.mutate(); } }} className="card mb-5 p-5" aria-labelledby="new-connector-heading">
      <h2 id="new-connector-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">New connector</h2>
      <fieldset className="mt-4">
        <legend className="mb-2 text-xs font-semibold text-slate-700">Type</legend>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {CONNECTOR_TYPES.map(type => <label key={type} className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-sm ${createType === type ? "border-[#11627a] bg-cyan-50/60 ring-1 ring-[#11627a]" : "border-slate-200 hover:bg-slate-50"}`}>
            <input type="radio" name="connector-type" value={type} checked={createType === type} onChange={() => { setCreateType(type); setCreateErrors({}); }} className="mt-1" />
            <span><span className="block font-bold text-slate-900">{connectorTypeLabels[type]}</span><span className="mt-0.5 block text-xs leading-5 text-slate-600">{connectorTypeDescriptions[type]}</span></span>
          </label>)}
        </div>
      </fieldset>
      <div className="mt-4"><ConnectorFields idPrefix="new" type={createType} mode="create" values={createValues} errors={createErrors} disabled={create.isPending} onChange={setCreateValues} /></div>
      {create.error && !isUnauthorizedError(create.error) && <p role="alert" className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{create.error.message}</p>}
      <div className="mt-5 flex flex-wrap gap-2">
        <button type="submit" className="primary !min-h-10 text-sm" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create connector"}</button>
        <button type="button" className="secondary !min-h-10 text-sm" disabled={create.isPending} onClick={() => { setCreating(false); setCreateValues(emptyConnectorForm); setCreateErrors({}); create.reset(); }}>Cancel</button>
      </div>
    </form>}

    <section aria-labelledby="connectors-heading" className="card overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-5"><h2 id="connectors-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Configured connectors</h2><p className="mt-1 text-xs leading-5 text-slate-500">Credentials are encrypted at rest and never returned. A connection test sends a signed test request (webhook), checks the table (Postgres), or reads the sheet (Google Sheets).</p></div>
      {connectors.isPending && <p role="status" className="px-6 py-10 text-center text-sm text-slate-500">Loading connectors…</p>}
      {connectors.isError && !isUnauthorizedError(connectors.error) && <p role="alert" className="px-6 py-8 text-sm text-rose-800">{connectors.error.message} <button type="button" className="font-semibold underline" onClick={() => connectors.refetch()}>Try again</button></p>}
      {connectors.isSuccess && list.length === 0 && <div className="px-6 py-10 text-center"><p className="font-semibold text-slate-700">No connectors yet</p><p className="mt-2 text-sm leading-6 text-slate-500">Create one, test it, then add a destination in the workflow configuration that maps document fields to it.</p></div>}
      {list.length > 0 && <ul className="divide-y divide-slate-100">
        {list.map(connector => <ConnectorRow
          key={connector.id}
          connector={connector}
          saving={update.isPending && update.variables?.connector.id === connector.id}
          testing={test.isPending && test.variables?.id === connector.id}
          testResult={testResults[connector.id]}
          error={rowErrors[connector.id] ?? null}
          onSave={(target, values) => {
            const type = isConnectorType(target.connector_type) ? target.connector_type : null;
            if (!type) return { name: "This connector type is not editable here." };
            const parsed = parseConnectorForm(type, "edit", values);
            if (!parsed.ok) return parsed.errors;
            setNotice("");
            update.mutate({ connector: target, body: connectorUpdateBody(target, parsed.value) });
            return null;
          }}
          onToggleActive={target => { setNotice(""); update.mutate({ connector: target, body: { version: target.version, active: !target.active } }); }}
          onTest={target => { setNotice(""); test.mutate(target); }}
        />)}
      </ul>}
    </section>

    <section aria-labelledby="exports-heading" className="card mt-5 overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-5"><h2 id="exports-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">CSV exports</h2><p className="mt-1 text-xs leading-5 text-slate-500">One file per connector per month, appended by executed export_csv actions. Reviewers and administrators can download them.</p></div>
      {connectors.isSuccess && csvConnectors.length === 0 && <p className="px-6 py-8 text-sm text-slate-500">No CSV export connector yet. Create one to collect approved rows into monthly files.</p>}
      {csvConnectors.length > 0 && <ul className="divide-y divide-slate-100">{csvConnectors.map(connector => <ExportsList key={connector.id} connector={connector} />)}</ul>}
    </section>
  </AppShell>;
}
