import { describe, expect, it } from "vitest";
import { apiErrorCode, apiErrorMessage, isUnauthorizedError, parseApiError, retryAfterMinutes, unauthorizedError, waitMessage } from "./errors";

describe("API error envelopes", () => {
  it("reads the server's code and message without trusting the shape", () => {
    expect(parseApiError({ error: { code: "conflict", message: "Version changed" } })).toEqual({ code: "conflict", message: "Version changed" });
    expect(parseApiError({ error: { message: 42 } })).toEqual({});
    expect(parseApiError("nope")).toEqual({});
    expect(parseApiError(null)).toEqual({});
    expect(apiErrorCode({ error: { code: "retry_limit_reached" } })).toBe("retry_limit_reached");
    expect(apiErrorCode(undefined)).toBeUndefined();
  });

  it("prefers the server message, then the caller's fallback, then a status default", () => {
    expect(apiErrorMessage({ error: { message: "Slug already taken" } }, 409, "fallback")).toBe("Slug already taken");
    expect(apiErrorMessage({ error: { message: "   " } }, 409, "fallback")).toBe("fallback");
    expect(apiErrorMessage({ error: { code: "conflict" } }, 409, "fallback")).toBe("fallback");
    expect(apiErrorMessage(undefined, 409)).toContain("changed");
    expect(apiErrorMessage(undefined, 503)).toContain("temporarily unavailable");
    expect(apiErrorMessage(undefined, 418)).toBe("The request failed. Please try again.");
  });

  it("recognizes the unauthorized sentinel and nothing else", () => {
    expect(isUnauthorizedError(unauthorizedError())).toBe(true);
    expect(isUnauthorizedError(new Error("Could not load"))).toBe(false);
    expect(isUnauthorizedError("Unauthorized")).toBe(false);
  });
});

describe("Retry-After parsing", () => {
  it("falls back when the header is missing or unreadable", () => {
    expect(retryAfterMinutes(null)).toBe(15);
    expect(retryAfterMinutes(undefined, 10)).toBe(10);
    expect(retryAfterMinutes("soon", 10)).toBe(10);
  });

  it("rounds delta-seconds up to whole minutes, never below one", () => {
    expect(retryAfterMinutes("120")).toBe(2);
    expect(retryAfterMinutes("61")).toBe(2);
    expect(retryAfterMinutes("0")).toBe(1);
  });

  it("accepts an HTTP date relative to now", () => {
    const now = Date.parse("2026-09-27T10:00:00Z");
    expect(retryAfterMinutes("Sun, 27 Sep 2026 10:10:00 GMT", 15, now)).toBe(10);
    expect(retryAfterMinutes("Sun, 27 Sep 2026 09:00:00 GMT", 15, now)).toBe(1);
  });

  it("words the wait for people", () => {
    expect(waitMessage(1)).toBe("1 minute");
    expect(waitMessage(15)).toBe("15 minutes");
  });
});
