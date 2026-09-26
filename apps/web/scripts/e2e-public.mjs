import assert from "node:assert/strict";
import { chromium } from "playwright-core";

const baseURL = (process.env.WEB_BASE_URL ?? "http://localhost:3300").replace(/\/$/, "");
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browser = await chromium.launch({ executablePath, headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const pageErrors = [];
page.on("pageerror", error => pageErrors.push(error.message));

const registrationPaths = [
  { path: "/register?mode=create", role: null },
  { path: "/register?mode=join&role=member", role: "member" },
  { path: "/register?mode=join&role=reviewer", role: "reviewer" },
];

async function landing() {
  const response = await page.goto(`${baseURL}/`);
  assert.equal(response?.status(), 200, "The public homepage did not return 200");
  assert.equal(new URL(page.url()).pathname, "/", "The public homepage redirected");
  await page.getByRole("main").waitFor();
  await page.getByRole("heading", { level: 1 }).waitFor();
}

async function registration(role) {
  assert.equal(new URL(page.url()).pathname, "/register");
  if (role) {
    await page.getByLabel("Requested role", { exact: true }).waitFor();
    await page.waitForFunction(expected => {
      return document.querySelector("#requested-role")?.value === expected;
    }, role);
    assert.equal(await page.getByLabel("Requested role", { exact: true }).inputValue(), role);
    await page.getByLabel("Organization", { exact: true }).waitFor();
    assert.equal(await page.getByLabel("Organization name", { exact: true }).count(), 0,
      "Joining an organization incorrectly shows the creation form");
    await page.getByRole("button", { name: "Request access", exact: true }).waitFor();
  } else {
    await page.getByLabel("Organization name", { exact: true }).waitFor();
    assert.equal(await page.getByLabel("Requested role", { exact: true }).count(), 0);
    await page.getByRole("button", { name: "Create workspace", exact: true }).waitFor();
  }
  for (const field of ["Email", "Password", "Confirm password"]) {
    await page.getByLabel(field, { exact: true }).waitFor();
  }
}

async function noOverflow(width) {
  await page.setViewportSize({ width, height: 844 });
  await page.evaluate(() => document.fonts.ready);
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  assert.ok(dimensions.document <= dimensions.viewport + 1 && dimensions.body <= dimensions.viewport + 1,
    `Landing overflows at ${width}px: ${JSON.stringify(dimensions)}`);
}

try {
  await landing();
  // Public marketing must be usable without an account or seeded workspace.
  // No registration is submitted and no application data is changed by this test.
  for (const anchor of ["#workspace", "#workflow", "#features"]) {
    await page.locator(`a[href="${anchor}"]`).first().waitFor();
    assert.equal(await page.locator(anchor).count(), 1, `Missing landing section ${anchor}`);
  }
  const skip = page.getByRole("link", { name: /skip to/i }).first();
  if (await skip.count()) {
    await page.keyboard.press("Tab");
    assert.equal(await skip.evaluate(element => element === document.activeElement), true,
      "The skip link is not the first keyboard target");
    await page.keyboard.press("Enter");
    const target = await skip.getAttribute("href");
    assert.ok(target?.startsWith("#"));
    assert.equal(new URL(page.url()).hash, target);
  }
  await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: "instant" }));
  await page.screenshot({ path: process.env.E2E_PUBLIC_DESKTOP_SCREENSHOT ?? "/tmp/opspilot-landing-desktop.png", fullPage: true });

  for (const { path, role } of registrationPaths) {
    await landing();
    await page.locator(`a[href="${path}"]`).first().click();
    await page.waitForURL(`${baseURL}${path}`);
    await registration(role);
    await page.goBack();
    await page.waitForURL(`${baseURL}/`);
    await page.getByRole("heading", { level: 1 }).waitFor();
    await page.goForward();
    await page.waitForURL(`${baseURL}${path}`);
    await registration(role);

    // Bookmarks and links opened in a new tab must choose the same form as client navigation.
    await page.goto(`${baseURL}${path}`);
    await registration(role);
  }
  console.log("Public homepage and owner/member/reviewer paths pass client navigation, direct entry, and browser history");

  await page.goto(`${baseURL}/register?mode=invalid&role=admin`);
  await registration(null);
  await page.getByLabel("Organization name", { exact: true }).fill("Example Workspace");
  await page.getByRole("button", { name: "Create organization", exact: true }).click();
  assert.equal(await page.getByLabel("Organization name", { exact: true }).inputValue(), "Example Workspace",
    "Clicking the selected registration mode discarded the organization draft");
  await page.goto(`${baseURL}/register?mode=join&role=admin`);
  await registration("member");
  console.log("Invalid registration parameters cannot select an elevated role");

  await landing();
  await page.locator('a[href="/login"]').first().click();
  await page.waitForURL(`${baseURL}/login`);
  for (const field of ["Organization", "Email", "Password"]) {
    await page.getByLabel(field, { exact: true }).waitFor();
  }
  await page.locator('a[href="/"]').first().click();
  await page.waitForURL(`${baseURL}/`);
  await page.goto(`${baseURL}/dashboard`);
  await page.waitForURL(`${baseURL}/login`);
  await page.getByRole("button", { name: "Sign in", exact: true }).waitFor();
  console.log("Sign-in has organization credentials; protected Dashboard redirects an unauthenticated visitor");

  for (const width of [390, 320]) {
    await landing();
    await noOverflow(width);
    await page.locator('summary[aria-label="Open navigation"]').click();
    await page.getByRole("navigation", { name: "Mobile navigation", exact: true }).getByRole("link", { name: "Choose your role", exact: true }).click();
    await page.waitForURL(`${baseURL}/#workspace`);
    // Exercise real mobile entry links; a responsive menu may collapse section links,
    // but getting started and signing in must remain available.
    await page.locator('a[href="/login"]').first().click();
    await page.waitForURL(`${baseURL}/login`);
    await page.getByLabel("Organization", { exact: true }).waitFor();
    await landing();
    await page.locator('a[href="/register?mode=join&role=reviewer"]').first().click();
    await page.waitForURL(`${baseURL}/register?mode=join&role=reviewer`);
    await registration("reviewer");
  }
  await landing();
  await noOverflow(390);
  await page.screenshot({ path: process.env.E2E_PUBLIC_MOBILE_SCREENSHOT ?? "/tmp/opspilot-landing-mobile.png", fullPage: true });
  assert.deepEqual(pageErrors, [], "Public entry produced browser runtime errors");
  console.log("PASS: Public entry, registration roles, protected-route access, and 390/320px landing navigation; no browser errors");
} catch (error) {
  await page.screenshot({ path: "/tmp/opspilot-public-failure.png", fullPage: true }).catch(() => {});
  throw error;
} finally {
  await browser.close();
}
