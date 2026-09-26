import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./route";

afterEach(() => {
  vi.restoreAllMocks();
  delete process.env.API_INTERNAL_URL;
});

describe("same-origin API proxy", () => {
  it("forwards session cookies, query strings, and request IDs", async () => {
    process.env.API_INTERNAL_URL = "http://api:8000";
    const upstream = new Response(JSON.stringify({ email: "demo@example.com" }), {
      status: 200,
      headers: {
        "content-type": "application/json",
        "x-request-id": "request-123",
      },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(upstream);
    const request = new NextRequest("http://localhost:3300/api/v1/auth/me?view=short", {
      headers: { cookie: "opspilot_session=test", "x-request-id": "request-123" },
    });

    const response = await GET(request, { params: Promise.resolve({ path: ["v1", "auth", "me"] }) });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [target, init] = fetchMock.mock.calls[0];
    expect(String(target)).toBe("http://api:8000/v1/auth/me?view=short");
    expect(new Headers(init?.headers).get("cookie")).toBe("opspilot_session=test");
    expect(new Headers(init?.headers).get("x-request-id")).toBe("request-123");
    expect(response.headers.get("x-request-id")).toBe("request-123");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ email: "demo@example.com" });
  });

  it("forwards multipart uploads and login cookies without changing the status", async () => {
    process.env.API_INTERNAL_URL = "http://api:8000";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", {
      status: 202,
      headers: { "set-cookie": "opspilot_session=token; HttpOnly; Path=/; SameSite=lax" },
    }));
    const form = new FormData();
    form.set("file", new File(["%PDF-1.4 sample"], "invoice.pdf", { type: "application/pdf" }));
    const request = new NextRequest("http://localhost:3300/api/v1/documents", {
      method: "POST",
      headers: { origin: "http://localhost:3300" },
      body: form,
    });

    const response = await POST(request, { params: Promise.resolve({ path: ["v1", "documents"] }) });

    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).get("content-type")).toContain("multipart/form-data; boundary=");
    expect(new Headers(init?.headers).get("origin")).toBe("http://localhost:3300");
    expect(Buffer.from(init?.body as ArrayBuffer).toString()).toContain("invoice.pdf");
    expect(response.status).toBe(202);
    expect(response.headers.get("set-cookie")).toContain("opspilot_session=token");
  });

  it("returns a useful error when the internal API is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("connect failed"));
    const request = new NextRequest("http://localhost:3300/api/v1/documents");

    const response = await GET(request, { params: Promise.resolve({ path: ["v1", "documents"] }) });

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      error: { code: "api_unavailable", message: "The API is temporarily unavailable" },
    });
  });

  it("rejects an oversized upload before contacting the API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const request = new NextRequest("http://localhost:3300/api/v1/documents", {
      method: "POST",
      headers: { "content-length": String(12 * 1024 * 1024) },
      body: "small placeholder",
    });

    const response = await POST(request, { params: Promise.resolve({ path: ["v1", "documents"] }) });

    expect(response.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
