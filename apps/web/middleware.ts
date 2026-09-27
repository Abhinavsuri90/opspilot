import { NextResponse, type NextRequest } from "next/server";

export const SESSION_COOKIE = "opspilot_session";
const PROTECTED_PREFIXES = ["/dashboard", "/inbox", "/review", "/insights", "/admin"];

/**
 * Cookie presence is only a fast path for obviously signed-out visitors; the API
 * validates every session. A visitor of /login who still holds a cookie is not
 * redirected here: the cookie is HttpOnly and may be stale, so only the page's
 * own /v1/auth/me check can tell, and a cookie-only redirect would bounce a stale
 * session between /login and /dashboard.
 */
export function decideRedirect(pathname: string, hasCookie: boolean): string | null {
  const isProtected = PROTECTED_PREFIXES.some(prefix => pathname === prefix || pathname.startsWith(`${prefix}/`));
  return isProtected && !hasCookie ? "/login" : null;
}

export function middleware(request: NextRequest) {
  const hasCookie = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  const destination = decideRedirect(request.nextUrl.pathname, hasCookie);
  if (!destination) return NextResponse.next();
  return NextResponse.redirect(new URL(destination, request.url));
}

export const config = {
  matcher: ["/dashboard/:path*", "/inbox/:path*", "/review/:path*", "/insights/:path*", "/admin/:path*"],
};
