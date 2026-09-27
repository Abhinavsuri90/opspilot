import { describe, expect, it } from "vitest";
import { decideRedirect } from "./middleware";

describe("edge session guard", () => {
  it("sends cookie-less visitors of protected pages to sign in", () => {
    for (const path of ["/dashboard", "/inbox", "/inbox/", "/review", "/actions", "/insights", "/admin", "/admin/members", "/settings/policies", "/settings/workflow"]) {
      expect(decideRedirect(path, false)).toBe("/login");
    }
  });

  it("lets a visitor with any session cookie through; the API decides whether it is valid", () => {
    for (const path of ["/dashboard", "/inbox", "/review", "/actions", "/insights", "/admin", "/settings/connectors"]) {
      expect(decideRedirect(path, true)).toBeNull();
    }
  });

  it("never redirects public pages, with or without a cookie", () => {
    for (const path of ["/", "/login", "/register", "/register/", "/api/v1/auth/me"]) {
      expect(decideRedirect(path, false)).toBeNull();
      expect(decideRedirect(path, true)).toBeNull();
    }
  });

  it("matches whole path segments only", () => {
    expect(decideRedirect("/dashboards", false)).toBeNull();
    expect(decideRedirect("/inboxes/1", false)).toBeNull();
  });
});
