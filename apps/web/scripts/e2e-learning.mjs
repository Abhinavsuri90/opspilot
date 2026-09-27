import assert from "node:assert/strict";
import { chromium } from "playwright-core";

const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3300";
const password = process.env.DEMO_PASSWORD;
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

if (!password) throw new Error("DEMO_PASSWORD is required for the learning browser smoke test");

const browser = await chromium.launch({ executablePath, headless: true });
let stage = "login";
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(20000);
  await page.goto(`${baseURL}/login`);
  await page.getByLabel("Organization", { exact: true }).fill("northwind");
  await page.getByLabel("Email", { exact: true }).fill("northwind@example.com");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL(`${baseURL}/dashboard`);
  stage = "dashboard_metrics";
  await page.getByRole("group", { name: "Model escalation" }).waitFor();
  await page.getByRole("heading", { name: "Weekly field accuracy" }).waitFor();
  await page.getByRole("region", { name: "Model usage" }).waitFor();

  stage = "guide";
  await page.getByRole("link", { name: "Guide", exact: true }).click();
  await page.getByRole("heading", { name: /From incoming PDF to a decision/ }).waitFor();
  await page.getByRole("heading", { name: "What each place is for" }).waitFor();

  stage = "policies";
  await page.getByRole("link", { name: "Policies", exact: true }).click();
  await page.getByRole("heading", { name: "Model spend guardrail" }).waitFor();
  assert.equal(await page.getByLabel("Daily cap (US cents)").inputValue(), "100");

  stage = "quality_lab";
  await page.getByRole("link", { name: "Quality lab", exact: true }).click();
  await page.getByRole("heading", { name: "Quality lab" }).waitFor();
  await page.getByRole("heading", { name: "Measured results" }).waitFor();
  stage = "learning_delta";
  await page.getByText("0.0 percentage points").waitFor();
  console.log("Dashboard model metrics, role guide, spend cap and synthetic quality report passed");
} catch (error) {
  // Fixed stage labels and exception class are safe to expose as public CI annotations.
  const kind = error instanceof Error ? error.name : "UnknownError";
  console.error(`::error::Learning browser smoke failed at ${stage}: ${kind}`);
  throw error;
} finally {
  await browser.close();
}
