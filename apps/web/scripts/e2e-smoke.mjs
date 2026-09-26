import { chromium } from "playwright-core";
import { fileURLToPath } from "node:url";

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
  const sample = fileURLToPath(new URL("../../../examples/northwind-invoice.pdf", import.meta.url));
  await page.getByLabel("Invoice PDF").setInputFiles(sample);
  await page.getByRole("button", { name: "Upload invoice" }).click();
  await page.getByText("NW-2026-001", { exact: true }).waitFor({ timeout: 30000 });
  if (process.env.E2E_INBOX_SCREENSHOT) {
    await page.getByRole("region", { name: "Extraction result" }).screenshot({ path: process.env.E2E_INBOX_SCREENSHOT });
  }
  await page.getByRole("link", { name: /Dashboard/ }).click();
  await page.waitForURL(`${baseURL}/dashboard`);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(`${baseURL}/login`);
  await page.goto(`${baseURL}/dashboard`);
  await page.waitForURL(`${baseURL}/login`);
  console.log("Browser login, invoice upload, extraction, and logout passed");
} finally {
  await browser.close();
}
