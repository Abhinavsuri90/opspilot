import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { chromium } from "playwright-core";

// Acceptance run for the Phase 4 intake channels against a fresh logistics
// organization: the template choice at registration, the multi-file uploader
// with purchase orders and delivery notes, an API key used from outside the
// browser, email intake through the local Mailpit server, near-duplicate
// detection, the KPI dashboard and phone-width layouts.
//
// The email step sends a message with `docker compose run --rm admin ...` from
// the repository root, so it needs the compose stack that serves WEB_BASE_URL.
const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3300";
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
const suffix = randomBytes(6).toString("hex");
const slug = `contoso-${suffix}`;
const orgName = `Contoso Logistics ${suffix}`;
const adminEmail = `admin-${suffix}@example.com`;
const password = `Intake1-${randomBytes(20).toString("hex")}`;
const keyName = "Warehouse scanner";
const run = promisify(execFile);

const purchaseOrder = Buffer.from(await readFile(new URL("../../../examples/contoso-purchase-order.pdf", import.meta.url)));
const deliveryNote = Buffer.from(await readFile(new URL("../../../examples/contoso-delivery-note.pdf", import.meta.url)));
assert.equal(purchaseOrder.subarray(0, 5).toString(), "%PDF-");
assert.equal(deliveryNote.subarray(0, 5).toString(), "%PDF-");

/** A copy of a sample with same-length byte patches, so the PDF's object offsets stay valid. */
function patched(source, replacements) {
  const pdf = Buffer.from(source);
  for (const [marker, replacement] of replacements) {
    assert.equal(replacement.length, marker.length, `${replacement} must be as long as ${marker}`);
    const position = pdf.indexOf(Buffer.from(marker));
    assert.ok(position >= 0, `${marker} missing from the sample`);
    pdf.write(replacement, position, "ascii");
  }
  return pdf;
}
const tag = () => randomBytes(2).toString("hex").toUpperCase();
const poNumberA = `PO-2026-${tag()}`;
const dnNumberA = `DN-2026-${tag()}`;
const poNumberApi = `PO-2026-${tag()}`;
const poNumberDup = `PO-2026-${tag()}`;
const uploads = {
  po: { name: `contoso-po-${suffix}.pdf`, pdf: patched(purchaseOrder, [["PO-2026-0042", poNumberA]]) },
  dn: { name: `contoso-dn-${suffix}.pdf`, pdf: patched(deliveryNote, [["DN-2026-0042", dnNumberA]]) },
  api: { name: `warehouse-po-${suffix}.pdf`, pdf: patched(purchaseOrder, [["PO-2026-0042", poNumberApi]]) },
  dupA: { name: `resend-a-${suffix}.pdf`, pdf: patched(purchaseOrder, [["PO-2026-0042", poNumberDup]]) },
  // Same supplier, number and total; only a noise line differs, so the content hash differs.
  dupB: { name: `resend-b-${suffix}.pdf`, pdf: patched(purchaseOrder, [["PO-2026-0042", poNumberDup], ["This is a fictional synthetic document", "This is a FICTIONAL synthetic document"]]) },
};

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
const sidebar = (page, name) => page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name, exact: true });

async function waitForExtraction(page, documentId) {
  return until(`extraction of ${documentId}`, async () => {
    const detail = await apiJson(page, "GET", `/v1/documents/${documentId}`);
    assert.equal(detail.status, 200, detail.text);
    if (detail.json.status === "failed") throw new Error(`Extraction failed: ${detail.json.failure_reason}`);
    return ["queued", "extracting", "validating"].includes(detail.json.status) ? null : detail.json;
  }, { timeoutMs: 120000 });
}

function fieldValue(detail, name) {
  return detail.fields.find(field => field.name === name)?.current_value;
}

/** Select files in the uploader, submit, and collect every upload response the page sends. */
async function uploadThroughForm(page, files) {
  const responses = [];
  const listener = async response => {
    if (new URL(response.url()).pathname.endsWith("/v1/documents") && response.request().method() === "POST") responses.push({ status: response.status(), json: await response.json().catch(() => null) });
  };
  page.on("response", listener);
  try {
    await page.getByLabel("Document PDFs").setInputFiles(files.map(file => ({ name: file.name, mimeType: "application/pdf", buffer: file.pdf })));
    const queue = page.getByRole("list", { name: "Upload queue" });
    for (const file of files) await queue.getByRole("listitem").filter({ hasText: file.name }).waitFor();
    await page.getByRole("button", { name: `Upload ${files.length} document${files.length === 1 ? "" : "s"}`, exact: true }).click();
    await until(`${files.length} upload responses`, async () => responses.length >= files.length ? responses : null, { timeoutMs: 60000, everyMs: 250 });
    for (const file of files) await queue.locator(`[data-testid="upload-item"][data-upload-status="accepted"]`).filter({ hasText: file.name }).waitFor();
  } finally {
    page.off("response", listener);
  }
  for (const response of responses) assert.equal(response.status, 202, `upload returned ${response.status}`);
  return responses.map(response => response.json);
}

async function assertNoHorizontalOverflow(page, path, label) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseURL}${path}`);
  await page.getByRole("heading", { level: 1 }).first().waitFor();
  await sleep(700);
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

  // 1. A logistics organization through the template choice.
  await admin.goto(`${baseURL}/register`);
  await admin.getByLabel("Organization name", { exact: true }).fill(orgName);
  await admin.getByLabel("Workspace ID", { exact: true }).fill(slug);
  const logistics = admin.getByRole("radio", { name: /^Logistics/ });
  assert.equal(await admin.getByRole("radio", { name: "Invoices", exact: false }).isChecked(), true, "Invoices should be the default template");
  await logistics.check();
  await admin.getByLabel("Default invoice currency").selectOption("EUR");
  await admin.getByLabel("Email", { exact: true }).fill(adminEmail);
  await admin.getByLabel("Password", { exact: true }).fill(password);
  await admin.getByLabel("Confirm password", { exact: true }).fill(password);
  const registered = await submitted(admin, "/v1/auth/register-organization", () => admin.getByRole("button", { name: "Create workspace", exact: true }).click(), 201);
  assert.equal(registered.role, "admin");
  await admin.waitForURL(`${baseURL}/dashboard`);
  await admin.getByRole("heading", { name: "Dashboard", exact: true }).waitFor();
  const workflow = await apiJson(admin, "GET", "/v1/settings/workflow");
  assert.equal(workflow.status, 200, workflow.text);
  assert.ok(workflow.json.yaml.includes("purchase_order") && workflow.json.yaml.includes("delivery_note"), "The logistics template did not configure purchase orders and delivery notes");
  console.log("Logistics organization registered through the template choice; workflow version 1 has purchase orders and delivery notes");

  // 2. Two documents in one selection through the multi-file uploader.
  await sidebar(admin, "Inbox").click();
  await admin.getByRole("heading", { name: "Document inbox", exact: true }).waitFor();
  const [poUpload, dnUpload] = await uploadThroughForm(admin, [uploads.po, uploads.dn]);
  assert.equal(poUpload.duplicate, false);
  assert.equal(dnUpload.duplicate, false);
  await admin.getByRole("status").getByText("2 documents uploaded.", { exact: false }).waitFor();
  const poDetail = await waitForExtraction(admin, poUpload.id);
  const dnDetail = await waitForExtraction(admin, dnUpload.id);
  assert.equal(poDetail.document_type, "purchase_order");
  assert.equal(dnDetail.document_type, "delivery_note");
  assert.equal(poDetail.source, "upload");
  assert.equal(fieldValue(poDetail, "po_number"), poNumberA);
  assert.equal(fieldValue(poDetail, "supplier"), "Cedar Freight Lines");
  assert.equal(fieldValue(poDetail, "total"), "4160.02");
  assert.equal(fieldValue(dnDetail, "delivery_note_number"), dnNumberA);
  assert.equal(fieldValue(dnDetail, "supplier"), "Sunrise Packaging");
  assert.equal(fieldValue(dnDetail, "received_by"), "P. Mehta");

  const detailPane = admin.getByRole("region", { name: "Extraction result" });
  const list = admin.locator('[aria-label="Document list"]');
  await list.locator(`button[data-document-type="delivery_note"]`).filter({ hasText: uploads.dn.name }).click();
  await detailPane.getByTestId("detail-document-type").getByText("Delivery note", { exact: true }).waitFor();
  await detailPane.getByText(dnNumberA, { exact: true }).waitFor({ timeout: 60000 });
  await list.locator(`button[data-document-type="purchase_order"]`).filter({ hasText: uploads.po.name }).click();
  await detailPane.getByTestId("detail-document-type").getByText("Purchase order", { exact: true }).waitFor();
  await detailPane.getByText(poNumberA, { exact: true }).waitFor({ timeout: 60000 });
  assert.ok((await list.locator('[data-source="upload"]').count()) >= 2, "Upload source badges missing from the list");

  const typeFiltered = admin.waitForResponse(response => response.url().includes("/api/v1/documents") && new URL(response.url()).searchParams.get("document_type") === "purchase_order");
  await admin.getByLabel("Document type", { exact: true }).selectOption("purchase_order");
  await typeFiltered;
  await until("the type filter to narrow the list", async () => (await list.locator("button").count()) === 1 && (await list.locator('button[data-document-type="purchase_order"]').count()) === 1 ? true : null, { timeoutMs: 15000, everyMs: 250 });
  await admin.getByLabel("Document type", { exact: true }).selectOption("");
  await until("the type filter to clear", async () => (await list.locator("button").count()) === 2 ? true : null, { timeoutMs: 15000, everyMs: 250 });
  console.log("Multi-file upload accepted a purchase order and a delivery note; both extracted with the right type, labels and fields; the type filter narrows the list");

  // 3. An API key created in settings and used from outside the browser.
  await admin.goto(`${baseURL}/settings/api-keys`);
  await admin.getByRole("heading", { name: "API keys", exact: true }).waitFor();
  await admin.getByLabel("Key name", { exact: true }).fill(keyName);
  const created = await submitted(admin, "/v1/settings/api-keys", () => admin.getByRole("button", { name: "Create key", exact: true }).click(), 201);
  const freshPanel = admin.getByTestId("fresh-key");
  await freshPanel.waitFor();
  const apiKey = (await admin.getByTestId("fresh-key-value").textContent()).trim();
  assert.equal(apiKey, created.key);
  assert.match(apiKey, /^opk_[0-9a-f]{8}_[A-Za-z0-9_-]{32,64}$/);
  await freshPanel.getByRole("button", { name: "Copy key", exact: true }).click();
  await freshPanel.getByRole("button", { name: /^(Copied|Select and copy manually)$/ }).waitFor();
  assert.ok((await admin.getByTestId("curl-example").textContent()).includes(`opk_${created.key_prefix}_<secret>`), "The curl example does not use the key prefix");
  assert.ok(!(await admin.getByTestId("curl-example").textContent()).includes(apiKey), "The curl example leaked the key");
  await freshPanel.getByRole("button", { name: "I have saved it", exact: true }).click();
  await freshPanel.waitFor({ state: "hidden" });
  const keyRow = admin.getByRole("list", { name: "API keys" }).getByRole("listitem").filter({ hasText: keyName });
  await keyRow.getByText("Active", { exact: true }).waitFor();
  await keyRow.getByText("Never used", { exact: false }).waitFor();

  const outside = await browser.newContext();
  const bad = await outside.request.post(`${baseURL}/api/v1/documents`, { headers: { authorization: `Bearer opk_00000000_${"0".repeat(32)}` }, multipart: { file: { name: uploads.api.name, mimeType: "application/pdf", buffer: uploads.api.pdf } } });
  assert.equal(bad.status(), 401, `An unknown key was accepted: ${await bad.text()}`);
  const viaKey = await outside.request.post(`${baseURL}/api/v1/documents`, { headers: { authorization: `Bearer ${apiKey}` }, multipart: { file: { name: uploads.api.name, mimeType: "application/pdf", buffer: uploads.api.pdf } } });
  assert.equal(viaKey.status(), 202, `Upload with the API key failed: ${await viaKey.text()}`);
  const apiUpload = await viaKey.json();
  assert.equal(apiUpload.source, "api");
  assert.equal(apiUpload.source_ref, `API key ${keyName}`);
  const polled = await outside.request.get(`${baseURL}/api/v1/documents/${apiUpload.id}`, { headers: { authorization: `Bearer ${apiKey}` } });
  assert.equal(polled.status(), 200, "Status polling with the API key failed");
  const apiDetail = await waitForExtraction(admin, apiUpload.id);
  assert.equal(apiDetail.document_type, "purchase_order");
  assert.equal(fieldValue(apiDetail, "po_number"), poNumberApi);

  await admin.goto(`${baseURL}/inbox?document=${apiUpload.id}`);
  await detailPane.getByText(uploads.api.name, { exact: true }).waitFor();
  const detailBadge = detailPane.locator('[data-source="api"]');
  await detailBadge.waitFor();
  assert.ok((await detailBadge.getAttribute("title")).includes(`API key ${keyName}`), "The API badge does not name the key");
  await list.locator(`button[data-source="api"]`).filter({ hasText: uploads.api.name }).waitFor();
  const sourceFiltered = admin.waitForResponse(response => response.url().includes("/api/v1/documents") && new URL(response.url()).searchParams.get("source") === "api");
  await admin.getByLabel("Source", { exact: true }).selectOption("api");
  await sourceFiltered;
  await until("the source filter to narrow the list", async () => (await list.locator("button").count()) === 1 ? true : null, { timeoutMs: 15000, everyMs: 250 });

  await admin.goto(`${baseURL}/settings/api-keys`);
  await keyRow.getByText("Last used", { exact: false }).waitFor();
  await keyRow.getByRole("button", { name: "Revoke", exact: true }).click();
  const revokeDialog = admin.getByTestId("revoke-key-dialog");
  await revokeDialog.waitFor();
  await submitted(admin, "/revoke", () => revokeDialog.getByRole("button", { name: "Revoke key", exact: true }).click());
  await keyRow.getByText("Revoked", { exact: true }).waitFor();
  const afterRevoke = await outside.request.get(`${baseURL}/api/v1/documents/${apiUpload.id}`, { headers: { authorization: `Bearer ${apiKey}` } });
  assert.equal(afterRevoke.status(), 401, "A revoked key still works");
  await outside.close();
  console.log("API key created, shown once, used for an upload with the API badge, and revoked");

  // 4. Email intake through the local Mailpit server.
  await admin.goto(`${baseURL}/settings/email-inbox`);
  await admin.getByRole("heading", { name: "Email inbox", exact: true }).waitFor();
  await admin.getByRole("radio", { name: /^Mailpit/ }).check();
  await admin.getByTestId("mailpit-address").getByText(`${slug}@opspilot.local`, { exact: true }).waitFor();
  const savedInbox = await submitted(admin, "/v1/settings/email-inbox", () => admin.getByRole("button", { name: "Save inbox", exact: true }).click());
  assert.equal(savedInbox.backend, "mailpit");
  assert.equal(savedInbox.address, `${slug}@opspilot.local`);
  assert.equal(savedInbox.active, true);
  await admin.getByTestId("inbox-health").getByText("Waiting for first poll", { exact: true }).waitFor();
  const tested = await submitted(admin, "/v1/settings/email-inbox/test", () => admin.getByRole("button", { name: "Test connection", exact: true }).click());
  assert.equal(tested.ok, true, `Inbox test failed: ${tested.message}`);
  await admin.getByTestId("inbox-last-test").getByText("Test passed", { exact: true }).waitFor();

  const subject = `Purchase order ${suffix}`;
  const body = "Hello,\nplease find the purchase order attached.\nRegards, Cedar Freight Lines";
  const sent = await run("docker", ["compose", "run", "--rm", "admin", "python", "/workspace/scripts/send_test_email.py", "--to", `${slug}@opspilot.local`, "--pdf", "/workspace/examples/contoso-purchase-order.pdf", "--subject", subject, "--body", body], { cwd: repoRoot, timeout: 180000 });
  assert.ok(sent.stdout.includes("Sent contoso-purchase-order.pdf"), `Unexpected send output: ${sent.stdout} ${sent.stderr}`);
  const emailed = await until("the emailed document to appear", async () => {
    const result = await apiJson(admin, "GET", "/v1/documents?source=email");
    assert.equal(result.status, 200, result.text);
    return result.json.find(item => item.filename === "contoso-purchase-order.pdf") ?? null;
  }, { timeoutMs: 150000, everyMs: 3000 });
  assert.equal(emailed.source, "email");
  const emailDetail = await waitForExtraction(admin, emailed.id);
  assert.ok(emailDetail.context_text?.includes("please find the purchase order attached"), `Message context missing: ${emailDetail.context_text}`);
  await admin.goto(`${baseURL}/inbox?document=${emailed.id}`);
  await detailPane.locator('[data-source="email"]').waitFor();
  await list.locator('button[data-source="email"]').filter({ hasText: "contoso-purchase-order.pdf" }).waitFor();
  const context = admin.getByTestId("message-context");
  await context.getByRole("heading", { name: "Message context" }).waitFor();
  await context.getByText("please find the purchase order attached", { exact: false }).waitFor();
  await admin.goto(`${baseURL}/settings/email-inbox`);
  await admin.getByTestId("inbox-health").getByText("Polling", { exact: true }).waitFor();
  const status = admin.getByTestId("inbox-status");
  await until("the status panel to count the message", async () => Number(await status.getByTestId("inbox-stat-messages_processed").textContent()) >= 1 ? true : null, { timeoutMs: 20000, everyMs: 1000 });
  assert.ok(Number(await status.getByTestId("inbox-stat-documents_created").textContent()) >= 1, "The status panel did not count the created document");
  await status.getByTestId("inbox-stat-last_polled").getByText(/\d/).waitFor();
  console.log("Mailpit inbox configured and tested; an emailed purchase order arrived with the Email badge and its message context");

  // 5. Near-duplicate detection: same supplier, number and total in a second file.
  await admin.goto(`${baseURL}/inbox`);
  const [firstResend] = await uploadThroughForm(admin, [uploads.dupA]);
  await waitForExtraction(admin, firstResend.id);
  const [secondResend] = await uploadThroughForm(admin, [uploads.dupB]);
  assert.notEqual(firstResend.id, secondResend.id, "The second resend was treated as an exact duplicate");
  const dupDetail = await waitForExtraction(admin, secondResend.id);
  assert.equal(dupDetail.status, "needs_review", "A near-duplicate must wait for a person");
  assert.equal(dupDetail.near_duplicates.length, 1);
  assert.equal(dupDetail.near_duplicates[0].document_id, firstResend.id);
  const banner = detailPane.getByTestId("near-duplicate-banner");
  await banner.waitFor();
  await banner.getByRole("button", { name: uploads.dupA.name, exact: true }).click();
  await detailPane.getByText(uploads.dupA.name, { exact: true }).first().waitFor();
  await admin.goto(`${baseURL}/review/${secondResend.id}`);
  const reviewBanner = admin.getByTestId("near-duplicate-banner");
  await reviewBanner.waitFor();
  assert.equal(new URL(await reviewBanner.getByRole("link", { name: uploads.dupA.name, exact: true }).getAttribute("href"), baseURL).pathname, `/review/${firstResend.id}`);
  const poField = admin.locator('li[data-field-name="po_number"]');
  await poField.locator("summary").click();
  await poField.getByText(/Possible duplicate/).waitFor();
  console.log("Near-duplicate flagged: the inbox and review views show the warning with a link to the earlier document");

  // 6. The KPI dashboard with its range control, type filter and chart.
  await admin.goto(`${baseURL}/dashboard`);
  const kpis = admin.getByRole("region", { name: "Key performance indicators" });
  await kpis.getByRole("group", { name: "Documents processed" }).waitFor();
  assert.equal(await kpis.locator('[role="group"][data-testid^="kpi-"]').count(), 7, "Expected seven KPI tiles");
  await until("the processed count to include this run", async () => Number((await kpis.getByRole("group", { name: "Documents processed" }).getByTestId("kpi-value").textContent()).replace(/,/g, "")) >= 5 ? true : null, { timeoutMs: 30000, everyMs: 1000 });
  await kpis.getByRole("group", { name: "Cost per document" }).getByText("Not tracked yet", { exact: true }).waitFor();
  await kpis.getByRole("group", { name: "Hours saved" }).getByText(/manual baseline/).waitFor();
  const figure = admin.getByRole("figure");
  await figure.locator("svg.recharts-surface").first().waitFor();
  const weekly = admin.waitForResponse(response => response.url().includes("/api/v1/metrics/overview") && new URL(response.url()).searchParams.get("days") === "7");
  await admin.getByRole("group", { name: "Range" }).getByRole("button", { name: "7 days", exact: true }).click();
  await weekly;
  assert.equal(await admin.getByRole("group", { name: "Range" }).getByRole("button", { name: "7 days", exact: true }).getAttribute("aria-pressed"), "true");
  const typed = admin.waitForResponse(response => response.url().includes("/api/v1/metrics/overview") && new URL(response.url()).searchParams.get("document_type") === "purchase_order");
  await admin.getByRole("form", { name: "KPI filters" }).getByLabel("Document type").selectOption("purchase_order");
  await typed;
  const toggle = admin.getByRole("group", { name: "Series to plot" }).getByRole("button", { name: "Completed", exact: true });
  await toggle.click();
  assert.equal(await toggle.getAttribute("aria-pressed"), "false");
  await admin.getByText("Show data", { exact: true }).click();
  await admin.getByRole("table").getByRole("rowheader").first().waitFor();
  await admin.getByText("What these numbers mean", { exact: true }).click();
  await admin.getByText("Documents processed", { exact: true }).nth(1).waitFor();
  console.log("Dashboard shows the seven KPI tiles, the definitions, the chart and its range, type and series controls");

  // 7. Phone width: no horizontal overflow on the new pages.
  await assertNoHorizontalOverflow(admin, "/dashboard", "Dashboard");
  await assertNoHorizontalOverflow(admin, "/settings/api-keys", "API keys");
  await assertNoHorizontalOverflow(admin, "/settings/email-inbox", "Email inbox");
  await assertNoHorizontalOverflow(admin, "/inbox", "Inbox");
  assert.deepEqual(pageErrors, [], "Browser encountered JavaScript errors");
  console.log("Template choice, multi-file upload, API key intake, email intake, near-duplicates, KPI dashboard and mobile layout passed");
} catch (error) {
  if (diagnosticPage) {
    await diagnosticPage.screenshot({ path: "/tmp/opspilot-intake-failure.png", fullPage: true }).catch(() => undefined);
    console.error("Browser failure screenshot: /tmp/opspilot-intake-failure.png");
    console.error("Visible alerts:", await diagnosticPage.getByRole("alert").allTextContents().catch(() => []));
    console.error("Browser script errors:", pageErrors);
  }
  throw error;
} finally {
  await browser.close();
}
