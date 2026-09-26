import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright-core";

const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3300";
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const suffix = randomBytes(6).toString("hex");
const slug = `workspace-${suffix}`;
const orgName = `Workspace verification ${suffix}`;
const adminEmail = `admin-${suffix}@example.com`;
const reviewerEmail = `reviewer-${suffix}@example.com`;
const memberEmail = `member-${suffix}@example.com`;
// A fresh test-only secret avoids depending on seeded users or reading a real .env.
const password = `Workspace1-${randomBytes(20).toString("hex")}`;

const browser = await chromium.launch({ executablePath, headless: true });
const pageErrors = [];
let diagnosticPage;

async function newPage() {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("console", message => {
    if (["warning", "error"].includes(message.type()) && /sandbox|pdf|plugin/i.test(message.text())) {
      console.log(`Browser document viewer diagnostic: ${message.text()}`);
    }
  });
  return page;
}

async function submitted(page, endpoint, action, expected = 200) {
  const responsePromise = page.waitForResponse(response => {
    return new URL(response.url()).pathname.endsWith(endpoint) && response.request().method() === "POST";
  });
  await action();
  const response = await responsePromise;
  assert.equal(response.status(), expected, `${endpoint} returned an unexpected status`);
  return response.status() === 204 ? null : response.json();
}

async function capture(page, path) {
  if (!path) return;
  await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: "instant" }));
  await page.screenshot({ path, fullPage: true });
}

async function signIn(page, email, expected = 200) {
  await page.goto(`${baseURL}/login`);
  await page.getByLabel("Organization", { exact: true }).fill(slug);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await submitted(page, "/v1/auth/login", () => page.getByRole("button", { name: "Sign in", exact: true }).click(), expected);
  if (expected === 200) await page.waitForURL(`${baseURL}/dashboard`);
}

async function requestAccess(page, email, requestedRole) {
  await page.goto(`${baseURL}/register`);
  await page.getByRole("button", { name: "Join organization", exact: true }).click();
  await page.getByLabel("Organization", { exact: true }).fill(slug);
  await page.getByLabel("Requested role").selectOption(requestedRole);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(password);
  const result = await submitted(page, "/v1/auth/join-organization", () => page.getByRole("button", { name: "Request access", exact: true }).click(), 201);
  assert.equal(result.status, "pending");
  await page.getByRole("heading", { name: "Waiting for approval" }).waitFor();
}

try {
  const admin = await newPage();
  diagnosticPage = admin;
  const reviewer = await newPage();
  const member = await newPage();

  await admin.goto(`${baseURL}/register`);
  await admin.getByLabel("Organization name", { exact: true }).fill(orgName);
  await admin.getByLabel("Workspace ID", { exact: true }).fill(slug);
  await admin.getByLabel("Default invoice currency").selectOption("USD");
  await admin.getByLabel("Email", { exact: true }).fill(adminEmail);
  await admin.getByLabel("Password", { exact: true }).fill(password);
  await admin.getByLabel("Confirm password", { exact: true }).fill(password);
  const registered = await submitted(admin, "/v1/auth/register-organization", () => admin.getByRole("button", { name: "Create workspace", exact: true }).click(), 201);
  assert.equal(registered.role, "admin");
  assert.equal(registered.org_slug, slug);
  await admin.waitForURL(`${baseURL}/dashboard`);
  await admin.getByRole("heading", { name: "Dashboard", exact: true }).waitFor();
  console.log("Fresh organization and administrator registered");

  await requestAccess(reviewer, reviewerEmail, "reviewer");
  await signIn(reviewer, reviewerEmail, 403);
  await reviewer.getByRole("alert").getByText(/awaiting approval/i).waitFor();
  await requestAccess(member, memberEmail, "member");

  await admin.getByRole("link", { name: "Admin", exact: true }).click();
  await admin.getByRole("heading", { name: "Member directory" }).waitFor();
  for (const [email, role] of [[reviewerEmail, "reviewer"], [memberEmail, "member"]]) {
    const row = admin.getByRole("region", { name: "Member directory" }).getByRole("listitem").filter({ hasText: email });
    await row.getByLabel(`Role for ${email}`, { exact: true }).selectOption(role);
    const decision = admin.waitForResponse(response => new URL(response.url()).pathname.endsWith("/decision") && response.request().method() === "POST");
    await row.getByRole("button", { name: "Approve access", exact: true }).click();
    assert.equal((await decision).status(), 200);
    await row.getByText("Active", { exact: true }).waitFor();
  }
  await signIn(reviewer, reviewerEmail);
  await signIn(member, memberEmail);
  await reviewer.goto(`${baseURL}/admin`);
  await reviewer.getByRole("heading", { name: "Admin access required" }).waitFor();
  console.log("Pending accounts denied sign-in; administrator approved reviewer and member; reviewer denied Admin access");

  await admin.getByRole("tab", { name: "Invoice categories", exact: true }).click();
  await admin.getByLabel("Category name", { exact: true }).fill("Office supplies");
  await admin.getByLabel("Description (optional)").fill("Workplace equipment and stationery");
  const category = await submitted(admin, "/v1/categories", () => admin.getByRole("button", { name: "Create category", exact: true }).click(), 201);
  await admin.getByRole("tabpanel").getByText("Office supplies", { exact: true }).waitFor();
  const categoryRow = admin.getByRole("tabpanel").getByRole("listitem").filter({ hasText: "Office supplies" });
  await submitted(admin, `/v1/categories/${category.id}`, () => categoryRow.getByRole("button", { name: "Archive", exact: true }).click());
  await categoryRow.getByText("Archived", { exact: true }).waitFor();
  await submitted(admin, `/v1/categories/${category.id}`, () => categoryRow.getByRole("button", { name: "Restore", exact: true }).click());
  await categoryRow.getByRole("button", { name: "Archive", exact: true }).waitFor();
  console.log("Category created, archived, and restored");

  await admin.getByRole("link", { name: "Inbox", exact: true }).click();
  const sample = await admin.request.get(`${baseURL}/sample-invoice.pdf`);
  assert.equal(sample.status(), 200);
  assert.equal((await sample.body()).subarray(0, 5).toString(), "%PDF-");
  const pdf = Buffer.from(await readFile(new URL("../../../examples/multipage-invoice.pdf", import.meta.url)));
  assert.equal(pdf.subarray(0, 5).toString(), "%PDF-");
  const originalNumber = Buffer.from("NW-2026-001");
  const position = pdf.indexOf(originalNumber);
  assert.ok(position >= 0, "Sample invoice number missing");
  const invoiceNumber = `WS-${randomBytes(4).toString("hex").toUpperCase()}`;
  assert.equal(invoiceNumber.length, originalNumber.length);
  pdf.write(invoiceNumber, position, "ascii");
  await admin.getByLabel("Invoice PDF").setInputFiles({ name: `workspace-${suffix}.pdf`, mimeType: "application/pdf", buffer: pdf });
  const document = await submitted(admin, "/v1/documents", () => admin.getByRole("button", { name: "Upload invoice" }).click(), 202);
  const detail = admin.getByRole("region", { name: "Extraction result" });
  await detail.getByText(invoiceNumber, { exact: true }).waitFor({ timeout: 60000 });
  const documentId = document.id;
  assert.ok(documentId);

  console.log("Fresh invoice extracted with expected invoice number");
  await admin.locator('select[name="category"]').selectOption(category.id);
  await admin.locator('select[name="reviewer"]').selectOption({ label: reviewerEmail });
  await admin.getByLabel("Verified amount", { exact: true }).fill("123.45");
  await admin.getByLabel("Currency (ISO code)", { exact: true }).fill("USD");
  const initialMetadata = await submitted(admin, `/v1/documents/${documentId}/metadata`, () => admin.getByRole("button", { name: "Save invoice details" }).click());
  // Keep edits in both forms while a second reviewer saves a competing change.
  // Polling must preserve drafts and writes must retain their original version.
  await admin.getByRole("button", { name: "Access", exact: true }).click();
  await admin.locator('select[name="visibility"]').selectOption("restricted");
  await admin.getByRole("button", { name: "Review & discuss", exact: true }).click();
  await admin.getByLabel("Verified amount", { exact: true }).fill("130.00");
  const concurrentEdit = await reviewer.request.post(`${baseURL}/api/v1/documents/${documentId}/metadata`, {
    headers: { Origin: baseURL }, data: { version: initialMetadata.version, verified_amount: "140.00", currency: "USD" },
  });
  assert.equal(concurrentEdit.status(), 200);
  await admin.getByText("This invoice changed while you were editing. Your draft is preserved; discard it to load the latest values before saving.", { exact: true }).waitFor({ timeout: 25000 });
  assert.equal(await admin.getByLabel("Verified amount", { exact: true }).inputValue(), "130.00", "Polling discarded the invoice draft");
  assert.equal(await admin.getByRole("button", { name: "Approve invoice", exact: true }).isDisabled(), true, "Unsaved fields could be bypassed by approving");
  await submitted(admin, `/v1/documents/${documentId}/metadata`, () => admin.getByRole("button", { name: "Save invoice details" }).click(), 409);
  await admin.getByRole("button", { name: "Discard invoice edits and load latest", exact: true }).click();
  await admin.getByLabel("Verified amount", { exact: true }).fill("123.45");
  await submitted(admin, `/v1/documents/${documentId}/metadata`, () => admin.getByRole("button", { name: "Save invoice details" }).click());
  await admin.getByRole("button", { name: "Access", exact: true }).click();
  assert.equal(await admin.locator('select[name="visibility"]').inputValue(), "restricted", "Metadata save discarded the independent sharing draft");
  await submitted(admin, `/v1/documents/${documentId}/sharing`, () => admin.getByRole("button", { name: "Save access", exact: true }).click(), 409);
  await admin.getByRole("button", { name: "Discard access edits and load latest", exact: true }).click();
  assert.equal(await admin.locator('select[name="visibility"]').inputValue(), "workspace");
  await admin.getByRole("button", { name: "Review & discuss", exact: true }).click();
  console.log("Concurrent edits preserve independent drafts and reject stale versions");
  await admin.getByLabel("Comment on invoice", { exact: true }).fill("Please verify this invoice against the purchase order.");
  await submitted(admin, `/v1/documents/${documentId}/comments`, () => admin.getByRole("button", { name: "Post comment" }).click(), 201);
  await admin.getByRole("region", { name: "Invoice discussion" }).getByText("Please verify this invoice against the purchase order.", { exact: true }).waitFor();

  const visibleBeforeRestriction = await member.request.get(`${baseURL}/api/v1/documents/${documentId}`);
  assert.equal(visibleBeforeRestriction.status(), 200);
  await admin.getByRole("button", { name: "Access", exact: true }).click();
  await admin.locator('select[name="visibility"]').selectOption("restricted");
  await submitted(admin, `/v1/documents/${documentId}/sharing`, () => admin.getByRole("button", { name: "Save access", exact: true }).click());
  const restricted = await member.request.get(`${baseURL}/api/v1/documents/${documentId}`);
  assert.equal(restricted.status(), 404, "Unshared member could see a restricted invoice");
  const assignedReviewer = await reviewer.request.get(`${baseURL}/api/v1/documents/${documentId}`);
  assert.equal(assignedReviewer.status(), 200, "Assigned reviewer lost invoice access");
  await admin.getByRole("checkbox", { name: new RegExp(memberEmail.replaceAll(".", "\\.")) }).check();
  await submitted(admin, `/v1/documents/${documentId}/sharing`, () => admin.getByRole("button", { name: "Save access", exact: true }).click());
  assert.equal((await member.request.get(`${baseURL}/api/v1/documents/${documentId}`)).status(), 200, "Explicit share did not grant invoice access");

  await admin.getByRole("button", { name: "Full document", exact: true }).click();
  const renderedPdf = admin.getByRole("img", { name: "Invoice PDF page 1 of 2", exact: true });
  await renderedPdf.waitFor();
  assert.ok(await renderedPdf.evaluate(canvas => {
    const image = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let darkPixels = 0;
    for (let index = 0; index < image.length; index += 4) if (image[index] < 180 && image[index + 1] < 180 && image[index + 2] < 180 && image[index + 3] > 0) darkPixels += 1;
    return darkPixels > 100;
  }), "The PDF canvas is blank");
  assert.equal(await admin.getByRole("button", { name: "Previous PDF page", exact: true }).isDisabled(), true);
  assert.equal(await admin.getByRole("button", { name: "Next PDF page", exact: true }).isDisabled(), false);
  await admin.getByText("Read page 1 text", { exact: true }).click();
  await admin.locator("details").getByText(invoiceNumber, { exact: false }).waitFor();
  await admin.getByRole("button", { name: "Next PDF page", exact: true }).click();
  await admin.getByRole("img", { name: "Invoice PDF page 2 of 2", exact: true }).waitFor();
  assert.equal(await admin.getByRole("button", { name: "Next PDF page", exact: true }).isDisabled(), true);
  assert.equal(await admin.getByRole("button", { name: "Previous PDF page", exact: true }).isDisabled(), false);
  await admin.getByText("Read page 2 text", { exact: true }).click();
  await admin.locator("details").getByText("Purchase order: PO-2026-014", { exact: false }).waitFor();
  if (process.env.E2E_WORKSPACE_INBOX_SCREENSHOT) await admin.getByRole("img", { name: "Invoice PDF page 2 of 2", exact: true }).screenshot({ path: "/tmp/opspilot-pdf-page2.png" });
  await admin.getByRole("button", { name: "Previous PDF page", exact: true }).click();
  await renderedPdf.waitFor();
  const fitWidth = await renderedPdf.evaluate(canvas => canvas.width);
  await admin.getByLabel("PDF zoom", { exact: true }).selectOption("1.5");
  await admin.waitForFunction(originalWidth => {
    const canvas = document.querySelector('canvas[aria-label="Invoice PDF page 1 of 2"]');
    return canvas && canvas.width > originalWidth;
  }, fitWidth);
  await admin.getByLabel("PDF zoom", { exact: true }).selectOption("1");
  await admin.waitForFunction(originalWidth => {
    const canvas = document.querySelector('canvas[aria-label="Invoice PDF page 1 of 2"]');
    return canvas && canvas.width === originalWidth;
  }, fitWidth);
  if (process.env.E2E_WORKSPACE_INBOX_SCREENSHOT) await renderedPdf.screenshot({ path: "/tmp/opspilot-pdf-viewer.png" });
  const originalPdf = await admin.request.get(`${baseURL}/api/v1/documents/${documentId}/file`);
  assert.equal(originalPdf.status(), 200);
  assert.equal((await originalPdf.body()).subarray(0, 5).toString(), "%PDF-");
  await capture(admin, process.env.E2E_WORKSPACE_INBOX_SCREENSHOT);

  await reviewer.goto(`${baseURL}/review`);
  diagnosticPage = reviewer;
  await reviewer.getByRole("heading", { name: "Review queue", exact: true }).waitFor();
  await reviewer.getByRole("link").filter({ hasText: `workspace-${suffix}.pdf` }).click();
  await reviewer.getByRole("region", { name: "Invoice discussion" }).getByText("Please verify this invoice against the purchase order.", { exact: true }).waitFor();
  await reviewer.getByLabel("Decision note (required to reject)").fill("Checked PDF and purchase order; amount matches.");
  const approved = await submitted(reviewer, `/v1/documents/${documentId}/review`, () => reviewer.getByRole("button", { name: "Approve invoice", exact: true }).click());
  assert.equal(approved.reviews.at(-1)?.decision, "approve");
  await reviewer.getByRole("button", { name: "Reopen review", exact: true }).waitFor();
  await capture(reviewer, process.env.E2E_WORKSPACE_REVIEW_SCREENSHOT);
  console.log("Restricted sharing, original PDF, comments, and reviewer approval passed");

  await reviewer.getByRole("button", { name: "Ask invoice", exact: true }).click();
  const answer = await submitted(reviewer, "/v1/workspace/questions", () => reviewer.getByRole("button", { name: "Summarize this invoice", exact: true }).click());
  assert.equal(answer.supported, true);
  await reviewer.getByRole("region", { name: "Invoice questions" }).getByText(/Checked against current records/).waitFor();

  await admin.goto(`${baseURL}/insights`);
  diagnosticPage = admin;
  await admin.getByRole("heading", { name: "Workspace insights", exact: true }).waitFor();
  const currencyRow = admin.getByRole("row").filter({ has: admin.getByRole("rowheader", { name: "USD", exact: true }) });
  await currencyRow.waitFor();
  assert.deepEqual((await currencyRow.getByRole("cell").allTextContents()).map(Number), [123.45, 0, 123.45, 0]);
  const totals = await submitted(admin, "/v1/workspace/questions", () => admin.getByRole("button", { name: "What is the total amount pending review?", exact: true }).click());
  assert.equal(totals.supported, true);
  assert.match(totals.answer, /USD 0(?:\.00)?/);

  await admin.goto(`${baseURL}/dashboard`);
  await admin.getByRole("heading", { name: "Dashboard", exact: true }).waitFor();
  await capture(admin, process.env.E2E_WORKSPACE_DASHBOARD_SCREENSHOT);
  for (const endpoint of ["/api/v1/documents", "/api/v1/workspace/summary"]) {
    const samples = [];
    const serverTiming = new Set();
    for (let index = 0; index < 20; index += 1) {
      const sample = await admin.evaluate(async path => {
        const started = performance.now();
        const response = await fetch(path, { credentials: "include", cache: "no-store" });
        await response.arrayBuffer();
        return { elapsed: performance.now() - started, status: response.status, serverTiming: response.headers.get("server-timing") };
      }, endpoint);
      assert.equal(sample.status, 200);
      samples.push(sample.elapsed);
      if (sample.serverTiming) serverTiming.add(sample.serverTiming);
    }
    samples.sort((a, b) => a - b);
    console.log(JSON.stringify({
      measurement: "Local sequential browser latency smoke; not a load-test SLO",
      endpoint, samples: samples.length,
      p50_ms: Number(samples[Math.ceil(samples.length * 0.50) - 1].toFixed(1)),
      p95_ms: Number(samples[Math.ceil(samples.length * 0.95) - 1].toFixed(1)),
      max_ms: Number(samples.at(-1).toFixed(1)),
      server_timing: [...serverTiming],
    }));
  }

  await admin.goto(`${baseURL}/admin`);
  const memberRow = admin.getByRole("region", { name: "Member directory" }).getByRole("listitem").filter({ hasText: memberEmail });
  await memberRow.getByRole("button", { name: "Suspend", exact: true }).click();
  const suspendResponse = admin.waitForResponse(response => new URL(response.url()).pathname.endsWith("/decision") && response.request().method() === "POST");
  await memberRow.getByRole("button", { name: "Confirm suspension", exact: true }).click();
  assert.equal((await suspendResponse).status(), 200);
  const suspendedSession = await member.request.get(`${baseURL}/api/v1/auth/me`);
  assert.ok([401, 403].includes(suspendedSession.status()), "Suspended member's existing session remained active");

  await admin.setViewportSize({ width: 390, height: 844 });
  await admin.reload();
  await admin.getByRole("heading", { name: "Admin", exact: true }).waitFor();
  const mobileLayout = await admin.evaluate(() => ({
    width: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    overflow: [...document.querySelectorAll("main *")].filter(element => element.getBoundingClientRect().right > window.innerWidth).slice(0, 8).map(element => ({ tag: element.tagName, className: element.className })),
  }));
  assert.ok(mobileLayout.documentWidth <= mobileLayout.width, `Admin overflows a mobile viewport: ${JSON.stringify(mobileLayout)}`);
  await capture(admin, process.env.E2E_WORKSPACE_SCREENSHOT);
  assert.deepEqual(pageErrors, [], "Browser encountered JavaScript errors");
  console.log("Fresh organization registration, pending approval, member roles, categories, extraction, comments, restricted sharing, PDF access, review approval, verified totals, questions, suspension, and mobile Admin passed");
} catch (error) {
  if (diagnosticPage) {
    await diagnosticPage.screenshot({ path: "/tmp/opspilot-workspace-failure.png", fullPage: true });
    console.error("Browser failure screenshot: /tmp/opspilot-workspace-failure.png");
    console.error("Visible alerts:", await diagnosticPage.getByRole("alert").allTextContents());
    console.error("Browser script errors:", pageErrors);
  }
  throw error;
} finally {
  await browser.close();
}
