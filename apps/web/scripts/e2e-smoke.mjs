import { chromium } from "playwright-core";
import { randomBytes } from "node:crypto";

const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3300";
const password = process.env.DEMO_PASSWORD;
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

if (!password) {
  throw new Error("DEMO_PASSWORD is required for the browser smoke test");
}

const browser = await chromium.launch({ executablePath, headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${baseURL}/login`, { waitUntil: "networkidle" });
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(`${baseURL}/dashboard`);
  await page.getByRole("heading", { name: "Your workspace is ready" }).waitFor();
  if (process.env.E2E_SCREENSHOT) {
    await page.screenshot({ path: process.env.E2E_SCREENSHOT, fullPage: true });
  }
  await page.getByRole("link", { name: "Open inbox" }).click();
  await page.waitForURL(`${baseURL}/inbox`);
  const sampleLink = page.getByRole("link", { name: "Download sample invoice" });
  const sampleUrl = new URL(await sampleLink.getAttribute("href"), baseURL);
  const sampleResponse = await page.request.get(sampleUrl.toString());
  if (!sampleResponse.ok()) throw new Error("The hosted sample invoice is unavailable");
  const sample = await sampleResponse.body();
  if (!sample.subarray(0, 5).equals(Buffer.from("%PDF-"))) {
    throw new Error("The hosted sample invoice is not a PDF");
  }
  const marker = Buffer.from("NW-2026-001");
  const position = sample.indexOf(marker);
  if (position < 0 || sample.indexOf(marker, position + 1) >= 0) {
    throw new Error("The hosted sample invoice does not have one editable invoice number");
  }
  const invoiceNumber = `NW-${randomBytes(4).toString("hex").toUpperCase()}`;
  const uniqueSample = Buffer.from(sample);
  uniqueSample.write(invoiceNumber, position, "ascii");
  await page.getByLabel("Invoice PDF").setInputFiles({
    name: "northwind-invoice.pdf",
    mimeType: "application/pdf",
    buffer: uniqueSample,
  });
  await page.getByRole("button", { name: "Upload invoice" }).click();
  await page.getByRole("region", { name: "Extraction result" })
    .getByText(invoiceNumber, { exact: true }).waitFor({ timeout: 30000 });
  if (process.env.E2E_INBOX_SCREENSHOT) {
    await page.getByRole("region", { name: "Extraction result" }).screenshot({ path: process.env.E2E_INBOX_SCREENSHOT });
  }

  // Exercise the retry control with a failed document without changing demo data.
  const failedId = "00000000-0000-4000-8000-000000000001";
  let failedStatus = "failed";
  let retryCalls = 0;
  let retryLimitReached = false;
  const failedDocument = () => ({
    id: failedId,
    filename: "retry-demo.pdf",
    status: failedStatus,
    size_bytes: 742,
    workflow_config_version: 1,
    failure_reason: failedStatus === "failed" ? "Temporary extraction failure" : null,
    created_at: new Date().toISOString(),
  });
  await page.route("**/api/v1/documents**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/documents" && route.request().method() === "GET") {
      return route.fulfill({ json: [failedDocument()] });
    }
    if (path === `/api/v1/documents/${failedId}` && route.request().method() === "GET") {
      return route.fulfill({ json: { ...failedDocument(), fields: [], provider: null } });
    }
    if (path === `/api/v1/documents/${failedId}/retry` && route.request().method() === "POST") {
      retryCalls += 1;
      if (retryLimitReached) {
        return route.fulfill({
          status: 409,
          json: { error: { code: "retry_limit_reached", message: "Manual retry limit reached for this document" } },
        });
      }
      failedStatus = "queued";
      return route.fulfill({ status: 202, json: failedDocument() });
    }
    return route.continue();
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Retry extraction" }).click();
  await page.getByText("Retry queued. The extraction result will update automatically.").waitFor();
  await page.getByText(/Status:\s*queued/i).waitFor();
  if (retryCalls !== 1) throw new Error(`Expected one retry request, received ${retryCalls}`);

  failedStatus = "failed";
  retryLimitReached = true;
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Retry extraction" }).click();
  await page.getByText("This invoice has reached its limit of two manual retries. Further retries are disabled.").waitFor();
  if (retryCalls !== 2 || !(await page.getByRole("button", { name: "Retry limit reached" }).isDisabled())) {
    throw new Error("The exhausted retry limit was not shown correctly");
  }
  await page.unroute("**/api/v1/documents**");

  await page.getByRole("link", { name: /Dashboard/ }).click();
  await page.waitForURL(`${baseURL}/dashboard`);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(`${baseURL}/login`);
  await page.goto(`${baseURL}/dashboard`);
  await page.waitForURL(`${baseURL}/login`);
  console.log("Browser login, invoice upload, extraction, retry UI, and logout passed");
} finally {
  await browser.close();
}
