import { chromium } from "playwright-core";

const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3300";
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const documentId = index => `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`;
const session = role => ({
  user_id: "00000000-0000-4000-8000-000000000099",
  org_id: "00000000-0000-4000-8000-000000000098",
  org_name: "Northwind",
  email: "northwind@example.com",
  role,
});
const summary = index => ({
  id: documentId(index),
  filename: `invoice-${index + 1}.pdf`,
  status: "failed",
  size_bytes: 1024,
  workflow_config_version: 1,
  failure_reason: "Temporary extraction failure",
  created_at: new Date().toISOString(),
});

let loginStatus = 401;
let logoutStatus = 502;
let meStatus = 200;
let sessionRole = "reviewer";
let listStatus = 503;
let detailStatus = 503;
let uploadStatus = 403;
let retryStatus = 403;
let retryCode = "forbidden";
let listCount = 0;

const browser = await chromium.launch({ executablePath, headless: true });
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(10_000);
  await page.route("**/api/v1/**", async route => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();
    if (pathname === "/api/v1/auth/login" && method === "POST") {
      return route.fulfill(loginStatus === 200
        ? { status: 200, json: session(sessionRole) }
        : { status: loginStatus, json: { error: { code: "request_failed" } } });
    }
    if (pathname === "/api/v1/auth/me" && method === "GET") {
      return route.fulfill(meStatus === 200
        ? { status: 200, json: session(sessionRole) }
        : { status: meStatus, json: { error: { code: "unauthorized" } } });
    }
    if (pathname === "/api/v1/auth/logout" && method === "POST") {
      return route.fulfill(logoutStatus === 204
        ? { status: 204, body: "" }
        : { status: logoutStatus, json: { error: { code: "api_unavailable" } } });
    }
    if (pathname === "/api/v1/documents" && method === "GET") {
      return route.fulfill(listStatus === 200
        ? { status: 200, json: Array.from({ length: listCount }, (_, index) => summary(index)) }
        : { status: listStatus, json: { error: { code: "request_failed" } } });
    }
    if (pathname === "/api/v1/documents" && method === "POST") {
      if (uploadStatus !== 202) {
        return route.fulfill({ status: uploadStatus, json: { error: { code: "request_failed" } } });
      }
      listCount = 1;
      return route.fulfill({ status: 202, json: { ...summary(0), duplicate: false } });
    }
    if (/^\/api\/v1\/documents\/[^/]+$/.test(pathname) && method === "GET") {
      const id = pathname.split("/").at(-1);
      const index = Number(id?.slice(-12)) - 1;
      return route.fulfill(detailStatus === 200
        ? { status: 200, json: { ...summary(index), fields: [], provider: null } }
        : { status: detailStatus, json: { error: { code: "request_failed" } } });
    }
    if (/^\/api\/v1\/documents\/[^/]+\/retry$/.test(pathname) && method === "POST") {
      return route.fulfill({ status: retryStatus, json: { error: { code: retryCode } } });
    }
    return route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });

  await page.goto(`${baseURL}/login`);
  await page.getByLabel("Organization").fill("northwind");
  await page.getByLabel("Email").fill("northwind@example.com");
  await page.getByLabel("Password", { exact: true }).fill("mock-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("alert").getByText("Invalid organization, email, or password.").waitFor();

  loginStatus = 429;
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("alert").getByText(/wait 15 minutes/).waitFor();

  loginStatus = 502;
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("alert").getByText(/temporarily unavailable/).waitFor();

  loginStatus = 200;
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(`${baseURL}/dashboard`);
  await page.getByRole("heading", { name: "Dashboard" }).waitFor();

  await page.goto(`${baseURL}/admin`);
  await page.getByRole("heading", { name: "Admin access required" }).waitFor();
  await page.getByRole("link", { name: "Return to dashboard" }).click();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("alert").getByText("Could not sign out. Please try again.").waitFor();
  await page.getByRole("link", { name: "Open inbox", exact: true }).first().click();
  await page.waitForURL(`${baseURL}/inbox`);
  await page.getByRole("alert").getByText(/Could not load documents/).waitFor();

  listStatus = 200;
  await page.getByRole("alert").getByRole("button", { name: "Try again" }).click();
  await page.getByText("No documents yet.", { exact: false }).waitFor();

  await page.getByLabel("Invoice PDF").setInputFiles({
    name: "invoice.txt", mimeType: "text/plain", buffer: Buffer.from("not a PDF"),
  });
  await page.getByRole("button", { name: "Upload invoice" }).click();
  await page.getByRole("alert").getByText("Choose a PDF invoice.").waitFor();

  await page.getByLabel("Invoice PDF").setInputFiles({
    name: "invoice.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 sample"),
  });
  for (const [status, message] of [
    [403, "Your account cannot upload invoices."],
    [409, "This workspace cannot accept another invoice."],
    [400, "The PDF could not be accepted."],
    [413, "The PDF could not be accepted."],
    [503, "The upload service is temporarily unavailable."],
  ]) {
    uploadStatus = status;
    await page.getByRole("button", { name: "Upload invoice" }).click();
    await page.getByRole("alert").getByText(message, { exact: false }).waitFor();
  }

  uploadStatus = 202;
  await page.getByRole("button", { name: "Upload invoice" }).click();
  await page.getByRole("status").getByText(/Invoice uploaded/).waitFor();
  await page.getByRole("region", { name: "Extraction result" })
    .getByRole("alert").getByText(/Could not load this document/).waitFor();

  detailStatus = 200;
  await page.getByRole("region", { name: "Extraction result" })
    .getByRole("button", { name: "Try again" }).click();
  await page.getByRole("button", { name: "Retry extraction" }).waitFor();

  for (const [status, code, message] of [
    [403, "forbidden", "Your account cannot retry this invoice."],
    [503, "api_unavailable", "The retry service is temporarily unavailable."],
    [409, "request_failed", "This invoice is no longer failed."],
    [409, "retry_limit_reached", "This invoice has reached its limit of two manual retries."],
  ]) {
    retryStatus = status;
    retryCode = code;
    await page.getByRole("button", { name: "Retry extraction" }).click();
    await page.getByRole("alert").getByText(message, { exact: false }).waitFor();
  }
  if (!(await page.getByRole("button", { name: "Retry limit reached" }).isDisabled())) {
    throw new Error("The UI did not disable retry after the API reported the limit");
  }

  listCount = 40;
  await page.reload();
  await page.getByRole("region", { name: "Documents" }).getByRole("button").last().waitFor();
  const list = page.locator('[aria-label="Document list"]');
  const { clientHeight, scrollHeight } = await list.evaluate(element => ({
    clientHeight: element.clientHeight, scrollHeight: element.scrollHeight,
  }));
  const result = await page.getByRole("region", { name: "Extraction result" }).boundingBox();
  if (scrollHeight <= clientHeight || !result || result.height > 900) {
    throw new Error("The Inbox layout did not contain a long document list");
  }
  await page.getByRole("searchbox", { name: "Search documents" }).fill("invoice-39.pdf");
  await page.waitForFunction(() => document.querySelectorAll('[aria-label="Document list"] button').length === 1);
  if (await list.getByRole("button").count() !== 1) {
    throw new Error("The document search did not narrow the list");
  }
  await page.getByRole("searchbox", { name: "Search documents" }).fill("");

  sessionRole = "viewer";
  await page.reload();
  await page.getByText("Your workspace role can view invoices but cannot upload them.").waitFor();
  if (await page.getByRole("button", { name: "Retry extraction" }).count()) {
    throw new Error("Viewer saw a retry action");
  }

  sessionRole = "reviewer";
  logoutStatus = 204;
  await page.goto(`${baseURL}/dashboard`);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(`${baseURL}/login`);

  meStatus = 401;
  await page.goto(`${baseURL}/dashboard`);
  await page.waitForURL(`${baseURL}/login`);
  console.log("Browser error states, role permissions, long-list layout, and session redirects passed");
} finally {
  await browser.close();
}
