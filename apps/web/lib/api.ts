import createClient from "openapi-fetch";
import type { paths } from "./schema";

export const api = createClient<paths>({
  baseUrl: "/api",
  credentials: "include",
});

// Cookies are shared across browser tabs. Invalidate other tabs when a login,
// organization switch or logout changes the identity behind those cookies.
api.use({
  async onResponse({ response, schemaPath }) {
    if (typeof window === "undefined") return response;
    const publicAuth = ["/v1/auth/login", "/v1/auth/register-organization", "/v1/auth/join-organization", "/v1/auth/logout"].includes(schemaPath);
    if (publicAuth && response.ok) {
      try { window.localStorage.setItem("opspilot.session-change", crypto.randomUUID()); } catch { /* Storage may be disabled by browser policy. */ }
    }
    if (!publicAuth && (response.status === 401 || (schemaPath === "/v1/auth/me" && response.status === 403))) {
      window.dispatchEvent(new Event("opspilot.session-lost"));
    }
    return response;
  },
});
