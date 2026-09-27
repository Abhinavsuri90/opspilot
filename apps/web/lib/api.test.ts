import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

type ApiModule = typeof import("./api");

const setItem = vi.fn();
const dispatchEvent = vi.fn();
const fetchMock = vi.fn<typeof fetch>();
let api: ApiModule["api"];

function jsonResponse(status: number, body: unknown = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

beforeAll(async () => {
  // The client captures fetch and Request when it is created, and a browser
  // resolves the relative base URL; both are arranged before the module loads.
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("Request", class extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" && input.startsWith("/") ? `http://localhost${input}` : input, init);
    }
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("window", { localStorage: { setItem }, dispatchEvent });
  ({ api } = await import("./api"));
});

afterEach(() => {
  setItem.mockClear();
  dispatchEvent.mockClear();
  fetchMock.mockReset();
});

const credentials = { org_slug: "northwind", email: "northwind@example.com", password: "secret-password-1" };

describe("cross-tab session signals", () => {
  it("tells other tabs when a sign-in succeeds", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { user_id: "u", org_id: "o", role: "admin" }));

    await api.POST("/v1/auth/login", { body: credentials });

    expect(setItem).toHaveBeenCalledWith("opspilot.session-change", expect.any(String));
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it("neither broadcasts a failed sign-in nor treats it as a lost session", async () => {
    fetchMock.mockResolvedValue(jsonResponse(401, { error: { code: "unauthorized" } }));

    await api.POST("/v1/auth/login", { body: credentials });

    expect(setItem).not.toHaveBeenCalled();
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it("raises session-lost when a protected call answers 401", async () => {
    fetchMock.mockResolvedValue(jsonResponse(401, { error: { code: "unauthorized" } }));

    await api.GET("/v1/documents");

    expect(dispatchEvent).toHaveBeenCalledOnce();
    expect((dispatchEvent.mock.calls[0][0] as Event).type).toBe("opspilot.session-lost");
    expect(setItem).not.toHaveBeenCalled();
  });

  it("treats a 403 from the session endpoint as a lost session", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { error: { code: "forbidden" } }));

    await api.GET("/v1/auth/me");

    expect(dispatchEvent).toHaveBeenCalledOnce();
    expect((dispatchEvent.mock.calls[0][0] as Event).type).toBe("opspilot.session-lost");
  });

  it("leaves a successful response untouched", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { email: "northwind@example.com" }));

    const result = await api.GET("/v1/auth/me");

    expect(result.response.status).toBe(200);
    expect(result.data).toMatchObject({ email: "northwind@example.com" });
    expect(dispatchEvent).not.toHaveBeenCalled();
  });
});
