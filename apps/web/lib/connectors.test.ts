import { describe, expect, it } from "vitest";
import { connectorCreateBody, connectorFormFromResponse, connectorUpdateBody, emptyConnectorForm, parseConnectorForm, parseHeaderLines, type ConnectorResponse } from "./connectors";

const form = (overrides: Partial<typeof emptyConnectorForm>) => ({ ...emptyConnectorForm, name: "Receiver", ...overrides });
const secret = "s".repeat(24);

describe("webhook connectors", () => {
  it("accepts an absolute URL with a 16+ character secret and turns header lines into a map", () => {
    const parsed = parseConnectorForm("webhook", "create", form({ url: "https://hooks.example.com/opspilot", secret, headers: "X-Tenant: acme\n\nAccept: application/json" }));
    expect(parsed).toEqual({ ok: true, value: { name: "Receiver", config: { url: "https://hooks.example.com/opspilot", headers: { "X-Tenant": "acme", Accept: "application/json" } }, credentials: { secret } } });
    if (parsed.ok) expect(connectorCreateBody("webhook", parsed.value)).toEqual({ name: "Receiver", connector_type: "webhook", config: parsed.value.config, credentials: { secret } });
  });

  it("rejects what the API rejects: short secrets, relative URLs, embedded credentials and reserved headers", () => {
    const short = parseConnectorForm("webhook", "create", form({ url: "https://hooks.example.com/x", secret: "tooshort" }));
    expect(short.ok ? null : short.errors.secret).toMatch(/16 characters/);
    const relative = parseConnectorForm("webhook", "create", form({ url: "/hooks/opspilot", secret }));
    expect(relative.ok ? null : relative.errors.url).toMatch(/absolute http/);
    const embedded = parseConnectorForm("webhook", "create", form({ url: "https://user:pw@hooks.example.com/x", secret }));
    expect(embedded.ok ? null : embedded.errors.url).toMatch(/credentials/);
    const reserved = parseConnectorForm("webhook", "create", form({ url: "https://hooks.example.com/x", secret, headers: "X-OpsPilot-Signature: fake" }));
    expect(reserved.ok ? null : reserved.errors.headers).toMatch(/cannot be overridden/);
    expect(parseHeaderLines("no separator")).toEqual({ error: expect.stringContaining("Name: value") });
    expect(parseHeaderLines("Bad Name!: x")).toEqual({ error: "Header name is invalid: Bad Name!" });
  });

  it("keeps stored credentials on edit unless a new secret is typed", () => {
    const kept = parseConnectorForm("webhook", "edit", form({ url: "https://hooks.example.com/x", secret: "" }));
    expect(kept).toMatchObject({ ok: true, value: { credentials: null } });
    const rotated = parseConnectorForm("webhook", "edit", form({ url: "https://hooks.example.com/x", secret }));
    expect(rotated).toMatchObject({ ok: true, value: { credentials: { secret } } });
    const invalid = parseConnectorForm("webhook", "edit", form({ url: "https://hooks.example.com/x", secret: "short" }));
    expect(invalid.ok).toBe(false);
  });
});

describe("csv export connectors", () => {
  it("defaults the prefix, validates its characters and never sends credentials", () => {
    const parsed = parseConnectorForm("csv_export", "create", form({ file_prefix: "" }));
    expect(parsed).toEqual({ ok: true, value: { name: "Receiver", config: { file_prefix: "export" }, credentials: null } });
    if (parsed.ok) expect(connectorCreateBody("csv_export", parsed.value)).toEqual({ name: "Receiver", connector_type: "csv_export", config: { file_prefix: "export" } });
    const bad = parseConnectorForm("csv_export", "create", form({ file_prefix: "-leading" }));
    expect(bad.ok ? null : bad.errors.file_prefix).toMatch(/letters, digits/);
  });
});

describe("postgres table connectors", () => {
  it("requires SQL identifiers and a DSN that names a host", () => {
    const parsed = parseConnectorForm("postgres_table", "create", form({ schema: "public", table: "ap_invoices", dsn: "postgresql://ops:pw@db.internal:5432/ledger" }));
    expect(parsed).toMatchObject({ ok: true, value: { config: { schema: "public", table: "ap_invoices" }, credentials: { dsn: "postgresql://ops:pw@db.internal:5432/ledger" } } });
    const conninfo = parseConnectorForm("postgres_table", "create", form({ schema: "public", table: "t", dsn: "host=db.internal dbname=ledger user=ops" }));
    expect(conninfo.ok).toBe(true);
    const bad = parseConnectorForm("postgres_table", "create", form({ schema: "1bad", table: "drop table", dsn: "postgresql:///ledger" }));
    expect(bad.ok ? null : bad.errors).toMatchObject({ schema: expect.stringContaining("identifier"), table: expect.stringContaining("identifier"), dsn: expect.stringContaining("host") });
  });
});

describe("google sheets connectors", () => {
  const account = JSON.stringify({ client_email: "bot@project.iam.gserviceaccount.com", private_key: "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n", token_uri: "https://oauth2.googleapis.com/token" });

  it("checks the spreadsheet id shape and the service account file's required keys", () => {
    const parsed = parseConnectorForm("google_sheets", "create", form({ spreadsheet_id: "1AbCdEfGhIjKlMnOp", sheet_name: "Invoices", service_account_json: account }));
    expect(parsed).toMatchObject({ ok: true, value: { config: { spreadsheet_id: "1AbCdEfGhIjKlMnOp", sheet_name: "Invoices" }, credentials: { service_account_json: account } } });
    const shortId = parseConnectorForm("google_sheets", "create", form({ spreadsheet_id: "short", sheet_name: "Invoices", service_account_json: account }));
    expect(shortId.ok ? null : shortId.errors.spreadsheet_id).toMatch(/10 to 200/);
    const noKey = parseConnectorForm("google_sheets", "create", form({ spreadsheet_id: "1AbCdEfGhIjKlMnOp", sheet_name: "Invoices", service_account_json: JSON.stringify({ client_email: "bot@x.y" }) }));
    expect(noKey.ok ? null : noKey.errors.service_account_json).toMatch(/private_key/);
    const notJson = parseConnectorForm("google_sheets", "create", form({ spreadsheet_id: "1AbCdEfGhIjKlMnOp", sheet_name: "Invoices", service_account_json: "{nope" }));
    expect(notJson.ok ? null : notJson.errors.service_account_json).toMatch(/valid JSON/);
  });
});

describe("editing an existing connector", () => {
  const connector: ConnectorResponse = {
    id: "c1", name: "Receiver", connector_type: "webhook", config: { url: "https://hooks.example.com/x", headers: { "X-Tenant": "acme" } }, has_credentials: true, active: true, version: 3,
    created_at: "2026-09-27T10:00:00Z", updated_at: "2026-09-27T10:00:00Z", last_test_at: null, last_test_ok: null, last_test_message: null, capabilities: {},
  };

  it("prefills the form from the response without ever seeing credentials", () => {
    const values = connectorFormFromResponse(connector);
    expect(values).toMatchObject({ name: "Receiver", url: "https://hooks.example.com/x", headers: "X-Tenant: acme", secret: "" });
  });

  it("sends the version, the whole config, and the name or credentials only when they changed", () => {
    const same = parseConnectorForm("webhook", "edit", connectorFormFromResponse(connector));
    expect(same.ok && connectorUpdateBody(connector, same.value)).toEqual({ version: 3, config: { url: "https://hooks.example.com/x", headers: { "X-Tenant": "acme" } } });
    const renamed = parseConnectorForm("webhook", "edit", { ...connectorFormFromResponse(connector), name: "Receiver 2", secret });
    expect(renamed.ok && connectorUpdateBody(connector, renamed.value)).toEqual({ version: 3, name: "Receiver 2", config: { url: "https://hooks.example.com/x", headers: { "X-Tenant": "acme" } }, credentials: { secret } });
  });
});
