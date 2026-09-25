import { describe, expect, it } from "vitest";
import { loginSchema } from "./login";

describe("login form validation", () => {
  it("accepts the seeded demo account format", () => {
    expect(loginSchema.safeParse({
      org_slug: "northwind",
      email: "northwind@example.com",
      password: "local-demo-only",
    }).success).toBe(true);
  });

  it("rejects an empty password before sending a request", () => {
    expect(loginSchema.safeParse({
      org_slug: "northwind",
      email: "northwind@example.com",
      password: "",
    }).success).toBe(false);
  });
});
