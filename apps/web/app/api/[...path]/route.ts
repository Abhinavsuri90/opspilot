import type { NextRequest } from "next/server";

type RouteContext = { params: Promise<{ path: string[] }> };
// Allow multipart framing around the API's 10 MB file limit.
const MAX_REQUEST_BYTES = 11 * 1024 * 1024;
// Only these request headers reach the API; everything else stops here.
const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "cookie", "origin", "sec-fetch-site", "x-request-id"];
// Only these response headers reach the browser. Content-Encoding is deliberately
// absent: fetch already decoded the body, so forwarding it would corrupt the response.
const FORWARDED_RESPONSE_HEADERS = ["content-type", "x-request-id", "content-disposition", "x-content-type-options", "content-security-policy", "server-timing", "retry-after"];

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

// A platform proxy sends the client chain in x-forwarded-for; a bare reverse
// proxy may only set x-real-ip. Next.js 15 exposes no socket address, so when
// neither header exists nothing is sent rather than a made-up value.
function clientChain(request: NextRequest): string | null {
  return request.headers.get("x-forwarded-for") ?? request.headers.get("x-real-ip");
}

function clientProtocol(request: NextRequest): string {
  return request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(/:$/, "");
}

async function forward(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  if (path[0] !== "v1" || path.some(segment => segment === "." || segment === "..")) {
    return new Response(null, { status: 404 });
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const chain = clientChain(request);
  if (chain) headers.set("x-forwarded-for", chain);
  headers.set("x-forwarded-proto", clientProtocol(request));

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
    for (const name of FORWARDED_RESPONSE_HEADERS) {
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

// The API only uses GET and POST; anything else is answered here without a round trip.
function methodNotAllowed(): Response {
  return new Response(null, { status: 405, headers: { allow: "GET, POST", "cache-control": "no-store" } });
}

export { forward as GET, forward as POST, methodNotAllowed as PUT, methodNotAllowed as PATCH, methodNotAllowed as DELETE };
