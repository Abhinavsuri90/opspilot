import type { NextRequest } from "next/server";

type RouteContext = { params: Promise<{ path: string[] }> };
// Allow multipart framing around the API's 10 MB file limit.
const MAX_REQUEST_BYTES = 11 * 1024 * 1024;

async function readLimitedBody(request: NextRequest): Promise<ArrayBuffer | null> {
  const declaredLength = Number(request.headers.get("content-length"));
  if (declaredLength > MAX_REQUEST_BYTES) return null;
  if (!request.body) return new ArrayBuffer(0);

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_REQUEST_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(new ArrayBuffer(total));
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}

async function forward(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  if (path[0] !== "v1" || path.some(segment => segment === "." || segment === "..")) {
    return new Response(null, { status: 404 });
  }

  const headers = new Headers();
  for (const name of ["accept", "content-type", "cookie", "origin", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const body = request.method === "GET" ? undefined : await readLimitedBody(request);
    if (body === null) {
      return Response.json(
        { error: { code: "request_too_large", message: "The upload exceeds the 10 MB file limit" } },
        { status: 413, headers: { "cache-control": "no-store" } },
      );
    }
    const apiBaseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const target = new URL(`/${path.map(encodeURIComponent).join("/")}`, apiBaseUrl);
    target.search = request.nextUrl.search;
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(60_000)]),
    });
    const responseHeaders = new Headers({ "cache-control": "no-store" });
    for (const name of ["content-type", "x-request-id"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    for (const cookie of upstream.headers.getSetCookie()) {
      responseHeaders.append("set-cookie", cookie);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json(
      { error: { code: "api_unavailable", message: "The API is temporarily unavailable" } },
      { status: 502, headers: { "cache-control": "no-store" } },
    );
  }
}

export { forward as GET, forward as POST };
