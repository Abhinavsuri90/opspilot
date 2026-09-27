import { describe, expect, it } from "vitest";
import { PASSWORD_MESSAGE, firstIssueMessage, registrationSchema } from "./register";

const create = {
  mode: "create" as const,
  org_name: " Acme Operations ",
  org_slug: " Acme-Ops ",
  default_currency: "usd",
  email: " Owner@Example.com ",
  password: "correct-horse-battery-9",
  confirmation: "correct-horse-battery-9",
};

function firstMessage(input: unknown) {
  const result = registrationSchema.safeParse(input);
  expect(result.success).toBe(false);
  return result.success ? "" : firstIssueMessage(result.error);
}

describe("registration validation", () => {
  it("normalizes a valid organization registration like the API does", () => {
    expect(registrationSchema.parse(create)).toMatchObject({
      mode: "create", org_name: "Acme Operations", org_slug: "acme-ops", default_currency: "USD", email: "owner@example.com",
    });
  });

  it("defaults the workflow template to invoices and accepts logistics", () => {
    expect(registrationSchema.parse(create)).toMatchObject({ template: "invoice" });
    expect(registrationSchema.parse({ ...create, template: "logistics" })).toMatchObject({ template: "logistics" });
    expect(firstMessage({ ...create, template: "shipping" })).toBe("Choose the documents your workspace starts with.");
  });

  it("reports the organization name before anything else", () => {
    expect(firstMessage({ ...create, org_name: "A", org_slug: "!!", password: "short" })).toBe("Enter an organization name with at least 2 characters.");
  });

  it("rejects a workspace ID that is not a slug", () => {
    for (const org_slug of ["-acme", "acme-", "acme ops", "a".repeat(81)]) {
      expect(firstMessage({ ...create, org_slug })).toContain("workspace ID");
    }
    expect(registrationSchema.safeParse({ ...create, org_slug: "a" }).success).toBe(true);
  });

  it("requires 12–128 characters with a letter and a digit", () => {
    for (const password of ["short1", "nodigitsatallhere", "123456789012", `${"x".repeat(128)}1`]) {
      expect(firstMessage({ ...create, password, confirmation: password })).toBe(PASSWORD_MESSAGE);
    }
    expect(registrationSchema.safeParse({ ...create, password: "ünïcödé-pässwörd-7", confirmation: "ünïcödé-pässwörd-7" }).success).toBe(true);
  });

  it("requires the confirmation to match", () => {
    expect(firstMessage({ ...create, confirmation: "correct-horse-battery-8" })).toBe("The passwords do not match.");
  });

  it("only accepts member or reviewer join requests", () => {
    const join = { mode: "join" as const, org_slug: "acme-ops", email: "new@example.com", password: create.password, confirmation: create.password };
    expect(registrationSchema.safeParse({ ...join, requested_role: "reviewer" }).success).toBe(true);
    expect(registrationSchema.safeParse({ ...join, requested_role: "admin" }).success).toBe(false);
    expect(registrationSchema.safeParse({ ...join, requested_role: "member", email: "not-an-email" }).success).toBe(false);
  });
});
