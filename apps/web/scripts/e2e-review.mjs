import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright-core";

// Acceptance run for the Phase 2 review experience: queue filters, the split
// view with evidence highlighting, keyboard-first field decisions, approval and
// the timeline, against a fresh organization so nothing depends on seeded data.
const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3300";
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const suffix = randomBytes(6).toString("hex");
const slug = `review-${suffix}`;
const orgName = `Review verification ${suffix}`;
const adminEmail = `admin-${suffix}@example.com`;
const password = `Review1-${randomBytes(20).toString("hex")}`;
const filename = `review-${suffix}.pdf`;

const browser = await chromium.launch({ executablePath, headless: true });
const pageErrors = [];
let diagnosticPage;

async function newPage() {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on("pageerror", error => pageErrors.push(error.message));
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

function editedValue(field) {
  switch (field.field_type) {
    case "date": return "2026-09-25";
    case "money": return "123.45";
    case "integer": return "7";
    case "currency": return "EUR";
    case "identifier": return `${field.current_value}-1`;
    default: return `${field.current_value} Ltd`;
  }
}

try {
  const admin = await newPage();
  diagnosticPage = admin;

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
  await admin.getByRole("region", { name: "Document summary" }).getByText("Auto-approved", { exact: true }).waitFor();
  console.log("Fresh organization registered; dashboard shows the auto-approved tile");

  await admin.getByRole("link", { name: "Inbox", exact: true }).click();
  const pdf = Buffer.from(await readFile(new URL("../../../examples/multipage-invoice.pdf", import.meta.url)));
  assert.equal(pdf.subarray(0, 5).toString(), "%PDF-");
  const originalNumber = Buffer.from("NW-2026-001");
  const position = pdf.indexOf(originalNumber);
  assert.ok(position >= 0, "Sample invoice number missing");
  const invoiceNumber = `RV-${randomBytes(4).toString("hex").toUpperCase()}`;
  assert.equal(invoiceNumber.length, originalNumber.length);
  pdf.write(invoiceNumber, position, "ascii");
  await admin.getByLabel("Invoice PDF").setInputFiles({ name: filename, mimeType: "application/pdf", buffer: pdf });
  const uploaded = await submitted(admin, "/v1/documents", () => admin.getByRole("button", { name: "Upload invoice" }).click(), 202);
  const documentId = uploaded.id;
  const detailPane = admin.getByRole("region", { name: "Extraction result" });
  await detailPane.getByText(invoiceNumber, { exact: true }).waitFor({ timeout: 60000 });
  const detailResponse = await admin.request.get(`${baseURL}/api/v1/documents/${documentId}`);
  assert.equal(detailResponse.status(), 200);
  const detail = await detailResponse.json();
  assert.equal(detail.status, "needs_review");
  assert.ok(detail.fields.length >= 3, "Expected several extracted fields");
  const flaggedFields = detail.fields.filter(field => field.status === "needs_review");
  assert.equal(detail.flagged_count, flaggedFields.length);

  // Inbox: compact confidence summary, a chip and a percentage per field, and the review link.
  const summaryBox = detailPane.locator('[aria-label="Confidence summary"]');
  await summaryBox.getByText(`${detail.flagged_count} flagged`, { exact: true }).waitFor();
  await summaryBox.getByText(`${detail.fields.filter(field => field.status === "auto").length} auto`, { exact: true }).waitFor();
  await summaryBox.getByText("0 corrected", { exact: true }).waitFor();
  assert.equal(await detailPane.locator("dl [data-status]").count(), detail.fields.length, "Every inbox field row shows a status chip");
  assert.equal(await detailPane.locator("dl").getByText(/^\d{1,3}%$/).count(), detail.fields.length, "Every inbox field row shows a confidence percentage");
  await detailPane.getByText("Evidence · page 1").first().waitFor();
  assert.equal(new URL(await summaryBox.getByRole("link", { name: "Open in review →" }).getAttribute("href"), baseURL).pathname, `/review/${documentId}`);
  console.log("Invoice extracted; inbox shows the confidence summary, status chips and review link");

  await admin.goto(`${baseURL}/review`);
  await admin.getByRole("heading", { name: "Review queue", exact: true }).waitFor();
  const row = admin.getByRole("link", { name: `Review ${filename}`, exact: true });
  await row.waitFor();
  const vendor = detail.fields.find(field => field.name === "vendor");
  if (vendor) await row.getByText(vendor.current_value, { exact: true }).waitFor();
  await row.getByText(`${detail.flagged_count} flagged`, { exact: true }).waitFor();
  await row.getByText(/Due in /).waitFor();
  await row.getByText("Unassigned", { exact: true }).waitFor();
  const queueRequest = admin.waitForRequest(request => request.url().includes("/api/v1/review/queue") && new URL(request.url()).searchParams.get("vendor") === "zzz-no-such-vendor");
  await admin.getByLabel("Vendor", { exact: true }).fill("zzz-no-such-vendor");
  await queueRequest;
  await admin.getByText("No invoices match these filters.").waitFor();
  await admin.getByRole("button", { name: "Clear filters", exact: true }).click();
  await row.waitFor();
  await admin.getByLabel("Overdue only", { exact: true }).check();
  await admin.getByText("No invoices match these filters.").waitFor();
  await admin.getByLabel("Overdue only", { exact: true }).uncheck();
  await row.waitFor();
  await capture(admin, process.env.E2E_REVIEW_QUEUE_SCREENSHOT);
  await admin.setViewportSize({ width: 390, height: 844 });
  await row.waitFor();
  const queueMobile = await admin.evaluate(() => ({ width: window.innerWidth, documentWidth: document.documentElement.scrollWidth }));
  assert.ok(queueMobile.documentWidth <= queueMobile.width, `Review queue overflows a mobile viewport: ${JSON.stringify(queueMobile)}`);
  await admin.setViewportSize({ width: 1280, height: 800 });
  await row.click();
  await admin.waitForURL(`${baseURL}/review/${documentId}`);
  console.log("Queue lists the invoice with vendor, flagged count and SLA; vendor and overdue filters produce a filtered empty state");

  const title = admin.getByRole("heading", { level: 1, name: filename });
  await title.waitFor();
  const fieldList = admin.getByRole("list", { name: "Extracted fields" });
  const rows = fieldList.getByRole("listitem");
  await rows.first().waitFor();
  assert.equal(await rows.count(), detail.fields.length);
  assert.equal(await fieldList.getByRole("meter").count(), detail.fields.length, "Every field shows a confidence meter");
  const percentages = await fieldList.getByTestId("confidence-percent").allTextContents();
  assert.equal(percentages.length, detail.fields.length);
  assert.ok(percentages.every(text => /^\d{1,3}%$/.test(text)), `Unexpected confidence labels: ${percentages.join(", ")}`);
  await admin.getByRole("region", { name: "Rule results" }).getByText("totals add up").waitFor();
  await admin.getByRole("region", { name: "Invoice discussion" }).waitFor();
  await admin.getByRole("img", { name: "Invoice PDF page 1 of 2", exact: true }).waitFor();

  // Evidence highlighting draws over the rendered page.
  const evidenceField = vendor ?? detail.fields[0];
  await admin.getByRole("button", { name: `Find evidence for ${evidenceField.label} on page ${evidenceField.page_number}`, exact: true }).click();
  await admin.getByText(`Evidence highlighted on page ${evidenceField.page_number}.`, { exact: true }).waitFor();
  assert.ok(await admin.getByTestId("evidence-highlight").locator("span").count() > 0, "No highlight rectangles were drawn");

  // Keyboard: the row whose button was clicked is the roving-focus start, so K walks
  // up to the first field; J moves down; Enter accepts a flagged field when there is one.
  await title.click();
  for (let step = 0; step < detail.fields.length; step += 1) await admin.keyboard.press("k");
  assert.equal(await rows.first().evaluate(element => document.activeElement === element), true, "K did not reach the first field");
  await admin.keyboard.press("j");
  assert.equal(await rows.nth(Math.min(1, detail.fields.length - 1)).evaluate(element => document.activeElement === element), true, "Second J did not move focus");
  await admin.keyboard.press("k");
  assert.equal(await rows.first().evaluate(element => document.activeElement === element), true, "K did not move focus back");
  let acceptedCount = 0;
  if (flaggedFields.length > 0) {
    const index = detail.fields.findIndex(field => field.status === "needs_review");
    for (let step = 0; step < index; step += 1) await admin.keyboard.press("j");
    const accepted = await submitted(admin, `/v1/documents/${documentId}/fields/${detail.fields[index].id}`, () => admin.keyboard.press("Enter"));
    assert.equal(accepted.fields.find(field => field.id === detail.fields[index].id).status, "approved");
    await rows.nth(index).getByText("Approved", { exact: true }).waitFor();
    acceptedCount = 1;
    for (let step = 0; step < index; step += 1) await admin.keyboard.press("k");
  }

  // E opens the typed inline editor on the focused field; Enter saves; a bad value shows the API reason inline.
  const firstField = detail.fields[0];
  await admin.keyboard.press("e");
  const editor = admin.getByLabel(`New value for ${firstField.label}`, { exact: true });
  await editor.waitFor();
  assert.equal(await editor.getAttribute("type"), firstField.field_type === "date" ? "date" : "text");
  const newValue = editedValue(firstField);
  await editor.fill(newValue);
  const corrected = await submitted(admin, `/v1/documents/${documentId}/fields/${firstField.id}`, () => admin.keyboard.press("Enter"));
  assert.equal(corrected.fields.find(field => field.id === firstField.id).status, "corrected");
  await rows.first().getByText("Corrected", { exact: true }).waitFor();
  await rows.first().getByText(newValue, { exact: true }).waitFor();
  await admin.getByTestId("field-summary").getByText(/1 corrected/).waitFor();
  assert.equal(await rows.first().evaluate(element => document.activeElement === element), true, "Focus did not return to the edited field");
  const moneyIndex = detail.fields.findIndex(field => field.field_type === "money");
  assert.ok(moneyIndex >= 0, "The invoice workflow has no money field to exercise a rejected edit");
  for (let step = 0; step < moneyIndex; step += 1) await admin.keyboard.press("j");
  await admin.keyboard.press("e");
  const moneyEditor = admin.getByLabel(`New value for ${detail.fields[moneyIndex].label}`, { exact: true });
  await moneyEditor.waitFor();
  assert.equal(await moneyEditor.getAttribute("inputmode"), "decimal");
  await moneyEditor.fill("abc");
  await submitted(admin, `/v1/documents/${documentId}/fields/${detail.fields[moneyIndex].id}`, () => admin.keyboard.press("Enter"), 422);
  await admin.getByRole("alert").filter({ hasText: "Value is not a valid amount" }).waitFor();
  await moneyEditor.waitFor();
  await admin.keyboard.press("Escape");
  await moneyEditor.waitFor({ state: "hidden" });
  assert.equal(await rows.nth(moneyIndex).evaluate(element => document.activeElement === element), true, "Escape did not return focus to the field");
  for (let step = 0; step < moneyIndex; step += 1) await admin.keyboard.press("k");
  console.log("Keyboard navigation, accept and typed edits work; invalid edits show the API reason inline");

  // "?" opens the modal shortcuts dialog, which traps focus and closes on Escape.
  await admin.keyboard.press("?");
  const shortcuts = admin.getByRole("dialog", { name: "Keyboard shortcuts", exact: true });
  await shortcuts.waitFor();
  assert.equal(await shortcuts.getAttribute("aria-modal"), "true");
  await shortcuts.getByText("Accept the focused field").waitFor();
  for (let step = 0; step < 3; step += 1) {
    await admin.keyboard.press("Tab");
    assert.equal(await shortcuts.evaluate(dialog => dialog.contains(document.activeElement)), true, "Focus escaped the shortcuts dialog");
  }
  await admin.keyboard.press("j");
  await shortcuts.waitFor();
  await admin.keyboard.press("Escape");
  await shortcuts.waitFor({ state: "hidden" });

  await admin.getByRole("tab", { name: "Timeline", exact: true }).click();
  const timeline = admin.getByRole("region", { name: "Document timeline" });
  await timeline.getByText(/^Extracted \d+ field\(s\) with /).waitFor();
  await timeline.getByText(`Edited ${firstField.name.replaceAll("_", " ")}`, { exact: true }).waitFor();
  await timeline.locator('[data-kind="correction"]').filter({ hasText: `Edited ${firstField.name.replaceAll("_", " ")}` }).getByText("Details", { exact: true }).click();
  await timeline.getByText(newValue, { exact: true }).waitFor();

  // A asks to confirm; confirming records the approval and completes the task.
  await admin.getByLabel("Decision note (required to reject)").fill("Checked every field against the PDF.");
  await title.click();
  await admin.keyboard.press("a");
  const approveDialog = admin.getByRole("dialog", { name: "Approve this invoice?", exact: true });
  await approveDialog.waitFor();
  const approved = await submitted(admin, `/v1/documents/${documentId}/review`, () => approveDialog.getByRole("button", { name: "Confirm approval", exact: true }).click());
  assert.equal(approved.reviews.at(-1)?.decision, "approve");
  await approveDialog.waitFor({ state: "hidden" });
  await admin.locator('header [data-tone="completed"]').getByText("Approved", { exact: true }).waitFor();
  await admin.getByRole("button", { name: "Reopen review", exact: true }).waitFor();
  await admin.getByText("Review approved", { exact: true }).waitFor();
  await timeline.getByText("Review decision: approve", { exact: true }).waitFor();
  assert.equal(await admin.getByRole("button", { name: /^Accept /, exact: false }).count(), 0, "Field actions stayed available after approval");
  await capture(admin, process.env.E2E_REVIEW_SCREENSHOT);
  console.log(`Approved via the A shortcut; timeline lists extraction, ${acceptedCount + 1} correction(s) and the review decision`);

  await admin.goto(`${baseURL}/review`);
  await admin.getByRole("heading", { name: "Review queue", exact: true }).waitFor();
  await admin.getByText("This queue is clear", { exact: true }).waitFor();

  await admin.setViewportSize({ width: 390, height: 844 });
  await admin.goto(`${baseURL}/review/${documentId}`);
  await title.waitFor();
  await admin.getByRole("img", { name: "Invoice PDF page 1 of 2", exact: true }).waitFor();
  const mobileLayout = await admin.evaluate(() => ({
    width: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    overflow: [...document.querySelectorAll("main *")].filter(element => element.getBoundingClientRect().right > window.innerWidth + 1).slice(0, 8).map(element => ({ tag: element.tagName, className: element.className })),
  }));
  assert.ok(mobileLayout.documentWidth <= mobileLayout.width, `Review page overflows a mobile viewport: ${JSON.stringify(mobileLayout)}`);
  await capture(admin, process.env.E2E_REVIEW_MOBILE_SCREENSHOT);
  assert.deepEqual(pageErrors, [], "Browser encountered JavaScript errors");
  console.log("Review queue filters, split view, evidence highlight, keyboard decisions, approval, timeline, and mobile layout passed");
} catch (error) {
  if (diagnosticPage) {
    await diagnosticPage.screenshot({ path: "/tmp/opspilot-review-failure.png", fullPage: true });
    console.error("Browser failure screenshot: /tmp/opspilot-review-failure.png");
    console.error("Visible alerts:", await diagnosticPage.getByRole("alert").allTextContents());
    console.error("Browser script errors:", pageErrors);
  }
  throw error;
} finally {
  await browser.close();
}
