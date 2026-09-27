import assert from "node:assert/strict";
import { createHmac, randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { chromium } from "playwright-core";

// Acceptance run for the Phase 3 agent control panel against a fresh organization:
// a webhook connector aimed at a receiver this script runs, a workflow destination,
// a needs-approval policy, the approve-and-deliver loop with HMAC verification, the
// kill switch (blocks, then resumes), shadow mode, a forbidden policy and mobile layout.
//
// The API runs in Docker, so it cannot reach this machine's 127.0.0.1. The connector
// URL therefore uses WEBHOOK_HOST (host.docker.internal on Docker Desktop; the docker0
// gateway such as 172.17.0.1 on a Linux runner). When that host is an IP literal the
// receiver binds every interface so the container's connection arrives.
const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3300";
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const webhookHost = process.env.WEBHOOK_HOST ?? "host.docker.internal";
const webhookBind = process.env.WEBHOOK_BIND ?? (/^\d+\.\d+\.\d+\.\d+$/.test(webhookHost) ? "0.0.0.0" : "127.0.0.1");
const suffix = randomBytes(6).toString("hex");
const slug = `actions-${suffix}`;
const orgName = `Actions verification ${suffix}`;
const adminEmail = `admin-${suffix}@example.com`;
const password = `Actions1-${randomBytes(20).toString("hex")}`;
const connectorName = `Receiver ${suffix}`;
const secret = randomBytes(12).toString("hex"); // 24 characters
assert.equal(secret.length, 24);

// The receiver records every request; tests and deliveries are told apart by their body.
const received = [];
const receiver = createServer((request, response) => {
  let body = "";
  request.setEncoding("utf8");
  request.on("data", chunk => { body += chunk; });
  request.on("end", () => {
    received.push({ method: request.method, url: request.url, headers: request.headers, body, at: Date.now() });
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ id: `receipt-${received.length}` }));
  });
});
await new Promise((resolve, reject) => { receiver.once("error", reject); receiver.listen(0, webhookBind, resolve); });
const receiverPort = receiver.address().port;
const webhookUrl = `http://${webhookHost}:${receiverPort}/hook`;
const deliveries = () => received.filter(item => item.url === "/hook" && !body(item).type);
function body(item) { try { return JSON.parse(item.body); } catch { return {}; } }
function assertSigned(item) {
  const timestamp = item.headers["x-opspilot-timestamp"];
  assert.ok(timestamp, "Delivery lacks X-OpsPilot-Timestamp");
  const expected = `sha256=${createHmac("sha256", secret).update(`${timestamp}.${item.body}`).digest("hex")}`;
  assert.equal(item.headers["x-opspilot-signature"], expected, "X-OpsPilot-Signature does not match HMAC(secret, timestamp.body)");
  assert.ok(item.headers["x-opspilot-idempotency-key"], "Delivery lacks an idempotency key");
  assert.equal(item.headers["content-type"], "application/json");
}

const browser = await chromium.launch({ executablePath, headless: true });
const pageErrors = [];
let diagnosticPage;

async function newPage() {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on("pageerror", error => pageErrors.push(error.message));
  return page;
}

async function submitted(page, endpoint, action, expected = 200) {
  const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(endpoint) && response.request().method() === "POST");
  await action();
  const response = await responsePromise;
  assert.equal(response.status(), expected, `${endpoint} returned ${response.status()}, expected ${expected}: ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}

async function apiJson(page, method, path, options = {}) {
  const response = await page.request.fetch(`${baseURL}/api${path}`, { method, ...options });
  const text = await response.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* not JSON */ }
  return { status: response.status(), json, text };
}

async function until(description, probe, { timeoutMs = 60000, everyMs = 1000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    last = await probe();
    if (last) return last;
    await new Promise(resolve => setTimeout(resolve, everyMs));
  }
  throw new Error(`Timed out waiting for ${description}`);
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
/** A sidebar link; settings pages repeat the same names in their tab strip. */
const sidebar = (page, name) => page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name, exact: true });

function toYaml(value, indent = 0) {
  const pad = " ".repeat(indent);
  const scalar = item => item === null || item === undefined ? "null" : typeof item === "string" ? JSON.stringify(item) : String(item);
  const lines = [];
  if (Array.isArray(value)) {
    for (const item of value) {
      if (item && typeof item === "object") {
        const inner = toYaml(item, indent + 2);
        lines.push(`${pad}- ${inner[0].slice(indent + 2)}`, ...inner.slice(1));
      } else {
        lines.push(`${pad}- ${scalar(item)}`);
      }
    }
    return lines;
  }
  for (const [key, item] of Object.entries(value)) {
    const name = /^[A-Za-z_][A-Za-z0-9_-]*$/.test(key) ? key : JSON.stringify(key);
    if (Array.isArray(item)) {
      if (item.length === 0) lines.push(`${pad}${name}: []`);
      else lines.push(`${pad}${name}:`, ...toYaml(item, indent));
    } else if (item && typeof item === "object") {
      if (Object.keys(item).length === 0) lines.push(`${pad}${name}: {}`);
      else lines.push(`${pad}${name}:`, ...toYaml(item, indent + 2));
    } else {
      lines.push(`${pad}${name}: ${scalar(item)}`);
    }
  }
  return lines;
}

const samplePdf = Buffer.from(await readFile(new URL("../../../examples/multipage-invoice.pdf", import.meta.url)));
assert.equal(samplePdf.subarray(0, 5).toString(), "%PDF-");
const sampleNumber = Buffer.from("NW-2026-001");
const numberOffset = samplePdf.indexOf(sampleNumber);
assert.ok(numberOffset >= 0, "Sample invoice number missing");
let uploads = 0;

/** A copy of the sample invoice with a unique invoice number, so no upload is a duplicate. */
function invoiceBytes() {
  uploads += 1;
  const pdf = Buffer.from(samplePdf);
  // Same length as NW-2026-001 so the patched bytes keep the PDF's object offsets valid.
  const invoiceNumber = `AC-${String(uploads).padStart(3, "0")}-${randomBytes(2).toString("hex").toUpperCase()}`;
  assert.equal(invoiceNumber.length, sampleNumber.length);
  pdf.write(invoiceNumber, numberOffset, "ascii");
  return { pdf, invoiceNumber, filename: `actions-${suffix}-${uploads}.pdf` };
}

async function waitForExtraction(page, documentId) {
  return until(`extraction of ${documentId}`, async () => {
    const detail = await apiJson(page, "GET", `/v1/documents/${documentId}`);
    assert.equal(detail.status, 200, detail.text);
    if (detail.json.status === "failed") throw new Error(`Extraction failed: ${detail.json.failure_reason}`);
    return detail.json.status === "needs_review" ? detail.json : null;
  }, { timeoutMs: 120000 });
}

/** Accept every flagged field through the API so the review can be approved. */
async function acceptFlaggedFields(page, documentId) {
  let detail = (await apiJson(page, "GET", `/v1/documents/${documentId}`)).json;
  for (const field of detail.fields.filter(item => item.status === "needs_review")) {
    const accepted = await apiJson(page, "POST", `/v1/documents/${documentId}/fields/${field.id}`, { data: { version: detail.version, action: "accept" } });
    assert.equal(accepted.status, 200, accepted.text);
    detail = accepted.json;
  }
  assert.equal(detail.flagged_count, 0);
  return detail;
}

/** Upload, wait for extraction, resolve flags and approve, all through the API; returns the detail. */
async function approvedInvoiceViaApi(page) {
  const { pdf, filename } = invoiceBytes();
  const uploaded = await apiJson(page, "POST", "/v1/documents", { multipart: { file: { name: filename, mimeType: "application/pdf", buffer: pdf } } });
  assert.equal(uploaded.status, 202, uploaded.text);
  await waitForExtraction(page, uploaded.json.id);
  const detail = await acceptFlaggedFields(page, uploaded.json.id);
  const review = await apiJson(page, "POST", `/v1/documents/${uploaded.json.id}/review`, { data: { version: detail.version, decision: "approve", comment: "Approved for the actions run" } });
  assert.equal(review.status, 200, review.text);
  return { ...detail, filename };
}

// A blocked action is deferred 60 s by the API and the worker polls every 2 s, so an
// execution can legitimately take a little over a minute to land.
const EXECUTION_WAIT_MS = 100000;

async function waitForAction(page, documentId, statuses, timeoutMs = EXECUTION_WAIT_MS) {
  return until(`an action for ${documentId} in ${statuses.join("/")}`, async () => {
    const list = await apiJson(page, "GET", `/v1/actions?document_id=${documentId}`);
    assert.equal(list.status, 200, list.text);
    return list.json.find(action => statuses.includes(action.status)) ?? null;
  }, { timeoutMs, everyMs: 2000 });
}

async function waitForDeliveries(count, timeoutMs = EXECUTION_WAIT_MS) {
  return until(`${count} webhook deliveries (have ${deliveries().length})`, async () => deliveries().length >= count ? deliveries() : null, { timeoutMs, everyMs: 2000 });
}

async function approveInPendingTab(page, filename) {
  await page.goto(`${baseURL}/actions`);
  await page.getByRole("tab", { name: "Pending approvals" }).click();
  const card = page.getByRole("article", { name: `post webhook for ${filename}`, exact: true });
  await card.waitFor({ timeout: 60000 });
  await card.getByText("Awaiting approval", { exact: true }).waitFor();
  const decided = await submitted(page, "/decision", () => card.getByRole("button", { name: "Approve", exact: true }).click());
  assert.equal(decided.status, "approved");
  await card.waitFor({ state: "hidden", timeout: 15000 });
  return decided;
}

async function historyCard(page, filename, status, timeoutMs = EXECUTION_WAIT_MS) {
  await page.goto(`${baseURL}/actions?tab=history`);
  const card = page.getByRole("article", { name: `post webhook for ${filename}`, exact: true });
  await card.waitFor();
  await page.locator(`article[data-status="${status}"]`).filter({ hasText: filename }).waitFor({ timeout: timeoutMs });
  return card;
}

async function flipKillSwitch(page, engage) {
  await page.goto(`${baseURL}/settings/policies`);
  const control = page.getByRole("switch", { name: "Kill switch" });
  await control.waitFor();
  assert.equal(await control.getAttribute("aria-checked"), String(!engage), "Kill switch was not in the expected starting state");
  await control.click();
  const dialog = page.getByRole("dialog", { name: engage ? "Pause the agent?" : "Resume the agent?", exact: true });
  await dialog.waitFor();
  const saved = await submitted(page, "/v1/settings/policies", () => dialog.getByRole("button", { name: engage ? "Pause agent" : "Resume agent", exact: true }).click());
  assert.equal(saved.kill_switch, engage);
  await dialog.waitFor({ state: "hidden" });
  const banner = page.getByTestId("agent-paused-banner");
  if (engage) await banner.waitFor(); else await banner.waitFor({ state: "hidden" });
  return saved;
}

async function setShadowMode(page, on) {
  await page.goto(`${baseURL}/settings/policies`);
  const control = page.getByRole("switch", { name: "Shadow mode" });
  await control.waitFor();
  assert.equal(await control.getAttribute("aria-checked"), String(!on));
  const saved = await submitted(page, "/v1/settings/policies", () => control.click());
  assert.equal(saved.shadow_mode, on);
  await page.getByText(on ? "Shadow mode on: approved actions are recorded, not executed." : "Shadow mode off: approved actions execute again.").waitFor();
}

async function setWebhookPolicy(page, mode) {
  await page.goto(`${baseURL}/settings/policies`);
  const select = page.getByLabel("Policy for post webhook", { exact: true });
  await select.waitFor();
  await select.selectOption(mode);
  await page.locator('[data-action-type="post_webhook"][data-dirty="true"]').waitFor();
  const saved = await submitted(page, "/v1/settings/policies", () => page.getByRole("button", { name: "Save policies", exact: true }).click());
  assert.equal(saved.policies.post_webhook, mode);
  await page.getByText(/Policies saved as version \d+\./).waitFor();
}

async function assertNoHorizontalOverflow(page, path, label) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseURL}${path}`);
  await page.getByRole("heading", { level: 1 }).first().waitFor();
  await sleep(500);
  const layout = await page.evaluate(() => ({
    width: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    overflow: [...document.querySelectorAll("main *")].filter(element => element.getBoundingClientRect().right > window.innerWidth + 1).slice(0, 8).map(element => ({ tag: element.tagName, className: String(element.className).slice(0, 80) })),
  }));
  assert.ok(layout.documentWidth <= layout.width, `${label} overflows a 390px viewport: ${JSON.stringify(layout)}`);
  await page.setViewportSize({ width: 1280, height: 800 });
}

try {
  const admin = await newPage();
  diagnosticPage = admin;

  // Fresh organization and administrator.
  await admin.goto(`${baseURL}/register`);
  await admin.getByLabel("Organization name", { exact: true }).fill(orgName);
  await admin.getByLabel("Workspace ID", { exact: true }).fill(slug);
  await admin.getByLabel("Default invoice currency").selectOption("USD");
  await admin.getByLabel("Email", { exact: true }).fill(adminEmail);
  await admin.getByLabel("Password", { exact: true }).fill(password);
  await admin.getByLabel("Confirm password", { exact: true }).fill(password);
  const registered = await submitted(admin, "/v1/auth/register-organization", () => admin.getByRole("button", { name: "Create workspace", exact: true }).click(), 201);
  assert.equal(registered.role, "admin");
  await admin.waitForURL(`${baseURL}/dashboard`);
  await admin.getByRole("heading", { name: "Dashboard", exact: true }).waitFor();
  await admin.getByTestId("tile-pending-approvals").waitFor();
  await admin.getByTestId("tile-dead-letters").waitFor();
  await sidebar(admin, "Actions").waitFor();
  await sidebar(admin, "Policies").waitFor();
  await sidebar(admin, "Connectors").waitFor();
  await sidebar(admin, "Workflow").waitFor();
  assert.equal(await admin.getByTestId("agent-paused-banner").count(), 0, "Banner shown while the kill switch is off");
  console.log(`Fresh organization registered; receiver listening on ${webhookBind}:${receiverPort}, reachable by the API as ${webhookUrl}`);

  // Connector: create a webhook aimed at the receiver, then test it.
  await sidebar(admin, "Connectors").click();
  await admin.getByRole("heading", { name: "Connectors", exact: true }).waitFor();
  await admin.getByText("No connectors yet", { exact: true }).waitFor();
  await admin.getByRole("button", { name: "New connector", exact: true }).click();
  await admin.getByRole("radio", { name: /^Webhook/ }).check();
  await admin.getByLabel("Name", { exact: true }).fill(connectorName);
  await admin.getByLabel("Endpoint URL", { exact: true }).fill(webhookUrl);
  await admin.getByLabel("Signing secret", { exact: true }).fill("short");
  await admin.getByRole("button", { name: "Create connector", exact: true }).click();
  await admin.getByRole("alert").filter({ hasText: "at least 16 characters" }).waitFor();
  await admin.getByLabel("Signing secret", { exact: true }).fill(secret);
  const created = await submitted(admin, "/v1/settings/connectors", () => admin.getByRole("button", { name: "Create connector", exact: true }).click(), 201);
  assert.equal(created.connector_type, "webhook");
  assert.equal(created.has_credentials, true);
  assert.equal(created.config.url, webhookUrl);
  assert.equal(created.config.secret, undefined, "Credentials leaked into the connector response");
  const row = admin.getByTestId("connector-row").filter({ hasText: connectorName });
  await row.getByText("Credentials stored", { exact: true }).waitFor();
  await row.getByText("Not tested yet.", { exact: true }).waitFor();
  const tested = await submitted(admin, "/test", () => row.getByRole("button", { name: "Test connection", exact: true }).click());
  assert.equal(tested.ok, true, `Connection test failed: ${tested.message}. Is ${webhookHost} reachable from the API container?`);
  await row.getByTestId("last-test").getByText("Test passed", { exact: true }).waitFor();
  const testRequest = received.find(item => body(item).type === "test");
  assert.ok(testRequest, "The receiver did not get the test request");
  assertSigned(testRequest);
  assert.equal(deliveries().length, 0);
  console.log("Webhook connector created with a stored secret; the connection test reached the receiver with a valid signature");

  // Workflow: import YAML built from the current config plus a destination; a broken file shows a line-referenced error first.
  const current = await apiJson(admin, "GET", "/v1/settings/workflow");
  assert.equal(current.status, 200, current.text);
  const config = current.json.config;
  config.destinations = [...(config.destinations ?? []), { name: "notify", connector: connectorName, action_type: "post_webhook", mapping: { vendor: "vendor", total: "total", file: "${document.filename}" } }];
  const yaml = `${toYaml(config).join("\n")}\n`;
  await sidebar(admin, "Workflow").click();
  await admin.getByRole("heading", { name: "Workflow", exact: true }).waitFor();
  const editor = admin.getByLabel("YAML", { exact: true });
  await editor.waitFor();
  assert.ok((await editor.inputValue()).includes("document_types:"), "Editor did not load the saved YAML");
  await admin.getByLabel("Import YAML", { exact: true }).setInputFiles({ name: "broken.yaml", mimeType: "application/yaml", buffer: Buffer.from("document_types:\n- name: invoice\n  fields: [\nreview_policy: always\n") });
  await admin.getByText(/Imported broken\.yaml/).waitFor();
  await submitted(admin, "/v1/settings/workflow", () => admin.getByRole("button", { name: /^Save as version/ }).click(), 422);
  const problems = admin.getByTestId("workflow-problem-list");
  await problems.waitFor();
  await problems.getByRole("button", { name: /Go to line \d+/ }).first().click();
  await admin.getByLabel("Import YAML", { exact: true }).setInputFiles({ name: "workflow.yaml", mimeType: "application/yaml", buffer: Buffer.from(yaml) });
  await admin.getByText(/Imported workflow\.yaml/).waitFor();
  assert.ok((await editor.inputValue()).includes("notify"), "Imported YAML did not reach the editor");
  await admin.getByLabel("Review SLA (minutes)", { exact: true }).fill("300");
  assert.match(await editor.inputValue(), /^review_sla_minutes: 300$/m, "SLA control did not rewrite the YAML");
  const savedWorkflow = await submitted(admin, "/v1/settings/workflow", () => admin.getByRole("button", { name: /^Save as version/ }).click());
  assert.equal(savedWorkflow.version, current.json.version + 1);
  assert.equal(savedWorkflow.config.review_sla_minutes, 300);
  assert.equal(savedWorkflow.config.destinations.at(-1).name, "notify");
  await admin.locator('[data-destination="notify"]').waitFor();
  await admin.getByText(`Saved as version ${savedWorkflow.version}.`, { exact: false }).waitFor();
  console.log(`Workflow imported and saved as version ${savedWorkflow.version} with the notify destination; a broken import showed a line-referenced 422`);

  // Policy: the webhook needs approval.
  await setWebhookPolicy(admin, "needs_approval");
  console.log("post_webhook policy set to needs approval");

  // Invoice 1 through the inbox and the review split view.
  await sidebar(admin, "Inbox").click();
  const first = invoiceBytes();
  await admin.getByLabel("Document PDFs").setInputFiles({ name: first.filename, mimeType: "application/pdf", buffer: first.pdf });
  const uploaded = await submitted(admin, "/v1/documents", () => admin.getByRole("button", { name: /^Upload \d+ document/ }).click(), 202);
  const firstId = uploaded.id;
  await admin.getByRole("region", { name: "Extraction result" }).getByText(first.invoiceNumber, { exact: true }).waitFor({ timeout: 90000 });
  const firstDetail = await acceptFlaggedFields(admin, firstId);
  const vendor = firstDetail.fields.find(field => field.name === "vendor");
  assert.ok(vendor?.current_value, "The sample invoice has no vendor value");
  await admin.goto(`${baseURL}/review/${firstId}`);
  await admin.getByRole("heading", { level: 1, name: first.filename }).waitFor();
  await admin.getByLabel("Decision note (required to reject)").fill("Approved in the actions run.");
  await admin.getByRole("button", { name: "Approve invoice", exact: true }).click();
  const approveDialog = admin.getByRole("dialog", { name: "Approve this invoice?", exact: true });
  await approveDialog.waitFor();
  await submitted(admin, `/v1/documents/${firstId}/review`, () => approveDialog.getByRole("button", { name: "Confirm approval", exact: true }).click());
  await admin.locator('header [data-tone="completed"], header [data-tone="actions"]').first().waitFor();
  console.log(`Invoice 1 (${first.filename}) extracted and approved in the split view; vendor is "${vendor.current_value}"`);

  // Pending approvals shows the proposal with a preview; approving it delivers a signed POST.
  await admin.goto(`${baseURL}/actions`);
  await admin.getByRole("heading", { name: "Actions", exact: true }).waitFor();
  const proposal = admin.getByRole("article", { name: `post webhook for ${first.filename}`, exact: true });
  await proposal.waitFor({ timeout: 60000 });
  await proposal.getByText("Awaiting approval", { exact: true }).waitFor();
  await proposal.getByText("Policy: Needs approval", { exact: true }).waitFor();
  await proposal.getByText(`via ${connectorName}`).waitFor();
  const previewTable = proposal.getByRole("table", { name: "Values the action sends" });
  await previewTable.getByRole("row", { name: /vendor/ }).getByText(vendor.current_value, { exact: true }).waitFor();
  await previewTable.getByRole("row", { name: /file/ }).getByText(first.filename, { exact: true }).waitFor();
  await proposal.getByText(`POST ${webhookUrl}`, { exact: true }).first().waitFor();
  await admin.getByTestId("count-pending").filter({ hasText: /^1$/ }).waitFor();
  // Rejecting needs a reason; cancel keeps the proposal.
  await proposal.getByRole("button", { name: "Reject", exact: true }).click();
  const rejectDialog = admin.getByRole("dialog", { name: "Reject this action?", exact: true });
  await rejectDialog.waitFor();
  assert.equal(await rejectDialog.getByRole("button", { name: "Reject action", exact: true }).isDisabled(), true, "Reject allowed without a reason");
  await rejectDialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await rejectDialog.waitFor({ state: "hidden" });
  const decided = await submitted(admin, "/decision", () => proposal.getByRole("button", { name: "Approve", exact: true }).click());
  assert.equal(decided.status, "approved");
  assert.equal(decided.decided_by_email, adminEmail);
  await admin.getByText(/^Approved post webhook for /).waitFor();
  await waitForAction(admin, firstId, ["succeeded"]);
  await waitForDeliveries(1);
  await historyCard(admin, first.filename, "succeeded");
  assert.equal(deliveries().length, 1, `Expected exactly one delivery, got ${deliveries().length}`);
  const firstDelivery = deliveries()[0];
  assertSigned(firstDelivery);
  const firstPayload = body(firstDelivery);
  assert.equal(firstPayload.document_id, firstId);
  assert.equal(firstPayload.action_type, "post_webhook");
  assert.equal(firstPayload.payload.vendor, vendor.current_value);
  assert.equal(firstPayload.payload.file, first.filename);
  const succeeded = admin.locator('article[data-status="succeeded"]').filter({ hasText: first.filename });
  await succeeded.getByText("Attempt history", { exact: false }).click();
  await succeeded.getByRole("list", { name: "Delivery attempts" }).getByText(/#1 ok/).waitFor();
  await succeeded.getByText(/HTTP 200/).first().waitFor();
  console.log("Proposal previewed and approved; the receiver got one signed POST carrying the vendor, and History shows the succeeded attempt");

  // The document's timeline links to the filtered Actions page.
  await admin.goto(`${baseURL}/review/${firstId}`);
  await admin.getByRole("heading", { level: 1, name: first.filename }).waitFor();
  // The PDF pane renders after the fields; the tab strip moves until it has. Wait for it, then click.
  await admin.getByRole("img", { name: /^Invoice PDF page 1/ }).waitFor({ timeout: 60000 });
  const timelineTab = admin.getByRole("tab", { name: "Timeline", exact: true });
  await timelineTab.scrollIntoViewIfNeeded();
  await timelineTab.click({ timeout: 60000 });
  const timeline = admin.getByRole("region", { name: "Document timeline" });
  await timeline.locator('[data-kind="action"]').first().waitFor();
  await timeline.getByText(/^Executed: post webhook to notify/).waitFor();
  await timeline.getByRole("link", { name: "View in Actions →" }).first().click();
  await admin.waitForURL(`${baseURL}/actions?document=${firstId}`);
  await admin.getByTestId("document-filter").getByText(first.filename, { exact: true }).waitFor();
  await admin.getByRole("tab", { name: "History" }).click();
  await admin.locator('article[data-status="succeeded"]').filter({ hasText: first.filename }).waitFor();
  console.log("Timeline shows the action events and deep-links to the Actions page filtered by document");

  // Kill switch: an approved action stays approved and nothing reaches the receiver.
  await flipKillSwitch(admin, true);
  const second = await approvedInvoiceViaApi(admin);
  await waitForAction(admin, second.id, ["proposed"]);
  await admin.goto(`${baseURL}/actions`);
  await admin.getByTestId("agent-paused-banner").waitFor();
  await approveInPendingTab(admin, second.filename);
  await sleep(5000);
  const blocked = await apiJson(admin, "GET", `/v1/actions?document_id=${second.id}`);
  assert.equal(blocked.json[0].status, "approved", `Action executed despite the kill switch: ${blocked.json[0].status}`);
  assert.equal(deliveries().length, 1, "The receiver got a request while the agent was paused");
  const blockedCard = await historyCard(admin, second.filename, "approved", 20000);
  await blockedCard.getByText("Agent paused: this action stays approved", { exact: false }).waitFor();
  await admin.getByTestId("agent-paused-banner").waitFor();
  console.log("Kill switch engaged: the approved action waited, the receiver stayed quiet, and the banner showed");

  // Disengaging lets the waiting action execute.
  await flipKillSwitch(admin, false);
  const resumed = await waitForAction(admin, second.id, ["succeeded"]);
  assert.equal(resumed.status, "succeeded");
  await waitForDeliveries(2);
  await historyCard(admin, second.filename, "succeeded");
  assert.equal(deliveries().length, 2, `Expected two deliveries after resuming, got ${deliveries().length}`);
  assertSigned(deliveries()[1]);
  assert.equal(body(deliveries()[1]).document_id, second.id);
  console.log("Kill switch disengaged: the waiting action executed and the receiver count reached two");

  // Shadow mode: approved actions are recorded as shadowed, nothing is sent.
  await setShadowMode(admin, true);
  const third = await approvedInvoiceViaApi(admin);
  await waitForAction(admin, third.id, ["proposed"]);
  await admin.goto(`${baseURL}/actions`);
  await admin.getByText("Shadow mode is on.", { exact: true }).waitFor();
  await approveInPendingTab(admin, third.filename);
  await waitForAction(admin, third.id, ["shadowed"]);
  await historyCard(admin, third.filename, "shadowed");
  assert.equal(deliveries().length, 2, "Shadow mode sent a real request");
  await setShadowMode(admin, false);
  console.log("Shadow mode: the approved action was recorded as shadowed and the receiver count stayed at two");

  // Forbidden policy: the proposal is recorded as forbidden without a human step.
  await setWebhookPolicy(admin, "forbidden");
  const fourth = await approvedInvoiceViaApi(admin);
  const forbidden = await waitForAction(admin, fourth.id, ["forbidden"]);
  assert.equal(forbidden.policy_mode, "forbidden");
  await admin.goto(`${baseURL}/actions?tab=history`);
  const filtered = admin.waitForResponse(response => response.url().includes("/api/v1/actions") && new URL(response.url()).searchParams.get("status") === "forbidden");
  await admin.getByLabel("Filter history by status", { exact: true }).selectOption("forbidden");
  await filtered;
  await admin.locator('article[data-status="forbidden"]').filter({ hasText: fourth.filename }).waitFor({ timeout: 30000 });
  // The previous page's rows may linger for a moment while the filtered answer renders.
  await until("the status filter to hide other outcomes", async () => (await admin.locator('article[data-status="succeeded"]').count()) === 0 ? true : null, { timeoutMs: 10000, everyMs: 250 });
  await admin.getByRole("tab", { name: "Pending approvals" }).click();
  await admin.getByText("Nothing awaits approval", { exact: true }).waitFor();
  await admin.getByRole("tab", { name: "Dead letters" }).click();
  await admin.getByText("No dead letters", { exact: true }).waitFor();
  assert.equal(deliveries().length, 2);
  console.log("Forbidden policy: the fourth invoice's action appeared as forbidden; pending and dead-letter tabs show their empty states");

  // Phone width: no horizontal overflow on the two busiest pages.
  await assertNoHorizontalOverflow(admin, "/actions?tab=history", "Actions");
  await assertNoHorizontalOverflow(admin, "/settings/policies", "Policies");
  await admin.goto(`${baseURL}/dashboard`);
  await admin.getByTestId("tile-dead-letters").getByText("0", { exact: true }).waitFor();
  assert.deepEqual(pageErrors, [], "Browser encountered JavaScript errors");
  console.log("Connectors, workflow import, policies, approval loop with HMAC verification, kill switch, shadow mode, forbidden policy and mobile layout passed");
} catch (error) {
  if (diagnosticPage) {
    await diagnosticPage.screenshot({ path: "/tmp/opspilot-actions-failure.png", fullPage: true }).catch(() => undefined);
    console.error("Browser failure screenshot: /tmp/opspilot-actions-failure.png");
    console.error("Visible alerts:", await diagnosticPage.getByRole("alert").allTextContents().catch(() => []));
    console.error("Browser script errors:", pageErrors);
    console.error("Receiver requests:", received.map(item => ({ url: item.url, type: body(item).type ?? "delivery", document_id: body(item).document_id })));
  }
  throw error;
} finally {
  await browser.close();
  receiver.close();
}
