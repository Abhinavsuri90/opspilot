import { z } from "zod";
import type { components } from "@/lib/schema";

export type ConnectorResponse = components["schemas"]["ConnectorResponse"];
export type ConnectorCreate = components["schemas"]["ConnectorCreate"];
export type ConnectorUpdate = components["schemas"]["ConnectorUpdate"];
export type ConnectorType = ConnectorCreate["connector_type"];

export const CONNECTOR_TYPES: readonly ConnectorType[] = ["webhook", "csv_export", "postgres_table", "google_sheets"];

export const connectorTypeLabels: Record<ConnectorType, string> = {
  webhook: "Webhook",
  csv_export: "CSV export",
  postgres_table: "Postgres table",
  google_sheets: "Google Sheets",
};

export const connectorTypeDescriptions: Record<ConnectorType, string> = {
  webhook: "POSTs a signed JSON body to your endpoint. Verify X-OpsPilot-Signature with the shared secret.",
  csv_export: "Appends a row to a monthly CSV file you can download from this page.",
  postgres_table: "Inserts a row into a table in your own database, keyed by the action id so retries never duplicate.",
  google_sheets: "Appends a row to a sheet using a service account you share the spreadsheet with.",
};

/** Which action type in the workflow config each connector type executes. */
export const connectorActionTypes: Record<ConnectorType, string> = {
  webhook: "post_webhook",
  csv_export: "export_csv",
  postgres_table: "create_record",
  google_sheets: "append_row",
};

export function isConnectorType(value: unknown): value is ConnectorType {
  return typeof value === "string" && (CONNECTOR_TYPES as readonly string[]).includes(value);
}

export function connectorTakesCredentials(type: ConnectorType): boolean {
  return type !== "csv_export";
}

// Mirrors the API's Pydantic models so the form rejects what the API would reject.
const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]{0,62}$/;
const FILE_PREFIX = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const SPREADSHEET_ID = /^[A-Za-z0-9_-]{10,200}$/;
const HEADER_NAME = /^[A-Za-z0-9-]{1,64}$/;
const RESERVED_HEADERS = new Set(["host", "content-length", "content-type", "transfer-encoding", "connection"]);
const MAX_SERVICE_ACCOUNT_BYTES = 16 * 1024;

export const connectorNameSchema = z.string().trim().min(1, "Give the connector a name.").max(100, "Keep the name under 100 characters.");

function absoluteHttpUrl(value: string, ctx: z.RefinementCtx) {
  let parsed: URL;
  try { parsed = new URL(value); } catch { ctx.addIssue({ code: "custom", message: "Enter an absolute http(s) URL." }); return; }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") { ctx.addIssue({ code: "custom", message: "The URL must start with https:// (http:// is only allowed in development)." }); return; }
  if (!parsed.hostname) { ctx.addIssue({ code: "custom", message: "The URL needs a host." }); return; }
  if (parsed.username || parsed.password) ctx.addIssue({ code: "custom", message: "Do not embed credentials in the URL; use the secret instead." });
}

/** "Name: value" per line, as the form collects static headers. Blank lines are ignored. */
export function parseHeaderLines(text: string): { headers: Record<string, string> } | { error: string } {
  const headers: Record<string, string> = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const separator = line.indexOf(":");
    if (separator <= 0) return { error: `Write headers as "Name: value" (line "${line.slice(0, 40)}").` };
    const name = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    if (!HEADER_NAME.test(name)) return { error: `Header name is invalid: ${name}` };
    const lowered = name.toLowerCase();
    if (RESERVED_HEADERS.has(lowered) || lowered.startsWith("x-opspilot-")) return { error: `Header ${name} is set by the connector and cannot be overridden.` };
    if (value.length > 1000 || /[\r\n\0]/.test(value)) return { error: `Header value for ${name} is invalid.` };
    headers[name] = value;
  }
  if (Object.keys(headers).length > 20) return { error: "Use at most 20 static headers." };
  return { headers };
}

const headersTextSchema = z.string().transform((text, ctx) => {
  const parsed = parseHeaderLines(text);
  if ("error" in parsed) { ctx.addIssue({ code: "custom", message: parsed.error }); return z.NEVER; }
  return parsed.headers;
});

export const webhookConfigSchema = z.object({
  url: z.string().trim().min(8, "Enter the endpoint URL.").max(2000, "The URL is too long.").superRefine(absoluteHttpUrl),
  headers: headersTextSchema,
});
export const webhookCredentialsSchema = z.object({
  secret: z.string().trim().min(16, "Use a secret of at least 16 characters.").max(512, "The secret is too long."),
});

export const csvExportConfigSchema = z.object({
  file_prefix: z.string().trim().transform(value => value || "export").pipe(z.string().regex(FILE_PREFIX, "Use letters, digits, dots, dashes or underscores, starting with a letter or digit (max 64).")),
});

export const postgresConfigSchema = z.object({
  schema: z.string().trim().regex(IDENTIFIER, "Use a plain SQL identifier (letters, digits, underscores)."),
  table: z.string().trim().regex(IDENTIFIER, "Use a plain SQL identifier (letters, digits, underscores)."),
});

function postgresDsnHasHost(value: string): boolean {
  const normalized = value.replace(/^postgres(ql)?\+psycopg(2)?:\/\//, "postgresql://");
  if (/^postgres(ql)?:\/\//.test(normalized)) {
    try { return new URL(normalized.replace(/^postgres:\/\//, "postgresql://")).hostname !== ""; } catch { return false; }
  }
  return /(^|\s)(host|hostaddr)=\S+/.test(normalized);
}

export const postgresCredentialsSchema = z.object({
  dsn: z.string().trim().min(12, "Enter the connection string.").max(2000, "The connection string is too long.").refine(postgresDsnHasHost, "Use a postgresql:// URL or key=value conninfo that names a host."),
});

export const googleSheetsConfigSchema = z.object({
  spreadsheet_id: z.string().trim().regex(SPREADSHEET_ID, "Paste the id from the spreadsheet URL (10 to 200 letters, digits, dashes or underscores)."),
  sheet_name: z.string().trim().min(1, "Enter the sheet (tab) name.").max(100, "Keep the sheet name under 100 characters."),
});

function serviceAccountJson(value: string, ctx: z.RefinementCtx) {
  if (new TextEncoder().encode(value).length > MAX_SERVICE_ACCOUNT_BYTES) { ctx.addIssue({ code: "custom", message: "The service account file is larger than 16 KB." }); return; }
  let decoded: unknown;
  try { decoded = JSON.parse(value); } catch { ctx.addIssue({ code: "custom", message: "The service account must be valid JSON." }); return; }
  if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) { ctx.addIssue({ code: "custom", message: "The service account must be a JSON object." }); return; }
  const record = decoded as Record<string, unknown>;
  if (typeof record.client_email !== "string" || !record.client_email.includes("@")) ctx.addIssue({ code: "custom", message: "The service account JSON lacks client_email." });
  if (typeof record.private_key !== "string" || !record.private_key.includes("PRIVATE KEY")) ctx.addIssue({ code: "custom", message: "The service account JSON lacks a PEM private_key." });
  if (record.token_uri !== undefined && (typeof record.token_uri !== "string" || !record.token_uri.startsWith("https://"))) ctx.addIssue({ code: "custom", message: "token_uri must be an https URL." });
}

export const googleSheetsCredentialsSchema = z.object({
  service_account_json: z.string().trim().min(2, "Paste the service account JSON.").superRefine(serviceAccountJson),
});

export const connectorConfigSchemas = {
  webhook: webhookConfigSchema,
  csv_export: csvExportConfigSchema,
  postgres_table: postgresConfigSchema,
  google_sheets: googleSheetsConfigSchema,
} as const;

export const connectorCredentialSchemas = {
  webhook: webhookCredentialsSchema,
  csv_export: null,
  postgres_table: postgresCredentialsSchema,
  google_sheets: googleSheetsCredentialsSchema,
} as const;

/** Every text field a connector form can show; each type reads the ones it needs. */
export type ConnectorFormValues = {
  name: string;
  url: string;
  headers: string;
  secret: string;
  file_prefix: string;
  schema: string;
  table: string;
  dsn: string;
  spreadsheet_id: string;
  sheet_name: string;
  service_account_json: string;
};

export const emptyConnectorForm: ConnectorFormValues = { name: "", url: "", headers: "", secret: "", file_prefix: "", schema: "public", table: "", dsn: "", spreadsheet_id: "", sheet_name: "", service_account_json: "" };

export function connectorFormFromResponse(connector: ConnectorResponse): ConnectorFormValues {
  const config = connector.config;
  const text = (key: string) => typeof config[key] === "string" ? String(config[key]) : "";
  const headers = config.headers && typeof config.headers === "object" && !Array.isArray(config.headers)
    ? Object.entries(config.headers as Record<string, unknown>).map(([name, value]) => `${name}: ${String(value)}`).join("\n")
    : "";
  return { ...emptyConnectorForm, name: connector.name, url: text("url"), headers, file_prefix: text("file_prefix"), schema: text("schema") || "public", table: text("table"), spreadsheet_id: text("spreadsheet_id"), sheet_name: text("sheet_name") };
}

export type ParsedConnector = { name: string; config: Record<string, unknown>; credentials: Record<string, unknown> | null };
export type ConnectorFieldErrors = Partial<Record<keyof ConnectorFormValues, string>>;
export type ConnectorParse = { ok: true; value: ParsedConnector } | { ok: false; errors: ConnectorFieldErrors };

function issuesToErrors(issues: z.core.$ZodIssue[]): ConnectorFieldErrors {
  const errors: ConnectorFieldErrors = {};
  for (const issue of issues) {
    const field = String(issue.path[0] ?? "name") as keyof ConnectorFormValues;
    if (!errors[field]) errors[field] = issue.message;
  }
  return errors;
}

/**
 * Validate a form the way the API will. On create every credential is required;
 * on edit blank credentials mean "keep what is stored", so they are only validated
 * (and only sent) when something was typed.
 */
export function parseConnectorForm(type: ConnectorType, mode: "create" | "edit", values: ConnectorFormValues): ConnectorParse {
  const errors: ConnectorFieldErrors = {};
  const name = connectorNameSchema.safeParse(values.name);
  if (!name.success) errors.name = name.error.issues[0]?.message ?? "Give the connector a name.";

  const config = connectorConfigSchemas[type].safeParse(values);
  if (!config.success) Object.assign(errors, issuesToErrors(config.error.issues));

  let credentials: Record<string, unknown> | null = null;
  const credentialSchema = connectorCredentialSchemas[type];
  if (credentialSchema) {
    const typed = Object.keys(credentialSchema.shape).some(key => values[key as keyof ConnectorFormValues].trim() !== "");
    if (mode === "create" || typed) {
      const parsed = credentialSchema.safeParse(values);
      if (!parsed.success) Object.assign(errors, issuesToErrors(parsed.error.issues));
      else credentials = parsed.data;
    }
  }

  if (Object.keys(errors).length > 0 || !name.success || !config.success) return { ok: false, errors };
  return { ok: true, value: { name: name.data, config: config.data, credentials } };
}

export function connectorCreateBody(type: ConnectorType, parsed: ParsedConnector): ConnectorCreate {
  return { name: parsed.name, connector_type: type, config: parsed.config, ...(parsed.credentials ? { credentials: parsed.credentials } : {}) };
}

/** Only what changed travels: the name when renamed, the config always (it is one unit), credentials only when re-entered. */
export function connectorUpdateBody(connector: Pick<ConnectorResponse, "version" | "name">, parsed: ParsedConnector): ConnectorUpdate {
  const body: ConnectorUpdate = { version: connector.version, config: parsed.config };
  if (parsed.name !== connector.name) body.name = parsed.name;
  if (parsed.credentials) body.credentials = parsed.credentials;
  return body;
}
