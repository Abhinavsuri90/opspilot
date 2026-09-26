import { chromium } from "playwright-core";
import { fileURLToPath } from "node:url";

const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3300";
const password = process.env.DEMO_PASSWORD;
const executablePath = process.env.PLAYWRIGHT_CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

if (!password) throw new Error("DEMO_PASSWORD is required for the tenant demo test");

const fixtures = {
  northwind: [
    ["northwind-harbor-supply.pdf", "NW-DEMO-2026-101"],
    ["northwind-maple-office.pdf", "NW-DEMO-2026-102"],
  ],
  contoso: [
    ["contoso-cedar-freight.pdf", "CT-DEMO-2026-201"],
    ["contoso-blue-ridge-parts.pdf", "CT-DEMO-2026-202"],
  ],
};

const browser = await chromium.launch({ executablePath, headless: true });
try {
  const page = await browser.newPage();

  async function signIn(org, email) {
    await page.goto(`${baseURL}/login`);
    await page.getByLabel("Organization").fill(org);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(`${baseURL}/dashboard`);
    await page.getByRole("heading", { name: "Dashboard" }).waitFor();
  }

  async function uploadFixture(filename, invoiceNumber) {
    await page.goto(`${baseURL}/inbox`);
    const path = fileURLToPath(new URL(`../../../examples/demo/${filename}`, import.meta.url));
    await page.getByLabel("Invoice PDF").setInputFiles(path);
    const uploaded = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/v1/documents" && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Upload invoice" }).click();
    const response = await uploaded;
    if (response.status() !== 202) throw new Error(`${filename} upload returned ${response.status()}`);
    const payload = await response.json();
    await page.getByRole("region", { name: "Extraction result" })
      .getByText(invoiceNumber, { exact: true }).waitFor({ timeout: 30_000 });
    return payload.id;
  }

  async function assertHiddenDocument(documentId, otherOrg) {
    const response = await page.request.get(`${baseURL}/api/v1/documents/${documentId}`);
    if (response.status() !== 404) {
      throw new Error(`${otherOrg} could read another organization's document: ${response.status()}`);
    }
  }

  await signIn("northwind", "northwind@example.com");
  await page.getByRole("link", { name: "Admin", exact: true }).waitFor();
  const northwindIds = [];
  for (const [filename, number] of fixtures.northwind) {
    northwindIds.push(await uploadFixture(filename, number));
  }
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(`${baseURL}/login`);

  await signIn("contoso", "contoso@example.com");
  if (await page.getByRole("link", { name: "Admin", exact: true }).count()) {
    throw new Error("Reviewer unexpectedly saw the Admin navigation link");
  }
  await page.goto(`${baseURL}/admin`);
  await page.getByRole("heading", { name: "Admin access required" }).waitFor();
  for (const id of northwindIds) await assertHiddenDocument(id, "Contoso");
  const contosoIds = [];
  for (const [filename, number] of fixtures.contoso) {
    contosoIds.push(await uploadFixture(filename, number));
  }
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(`${baseURL}/login`);

  await signIn("northwind", "northwind@example.com");
  for (const id of contosoIds) await assertHiddenDocument(id, "Northwind");
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(`${baseURL}/login`);
  console.log("Four fictional invoices extracted; both organizations were isolated; admin role was enforced");
} finally {
  await browser.close();
}
