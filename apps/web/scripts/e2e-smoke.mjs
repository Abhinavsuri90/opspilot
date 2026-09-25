import { chromium } from "playwright-core";

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
  console.log("Browser login and empty dashboard passed");
} finally {
  await browser.close();
}
