import { z } from "zod";

// The API wraps failures as `{ error: { code, message } }`. Parse, never cast.
const apiErrorSchema = z.object({
  error: z.object({ code: z.string().optional(), message: z.string().optional() }),
});

export type ApiError = { code?: string; message?: string };

export function parseApiError(body: unknown): ApiError {
  const parsed = apiErrorSchema.safeParse(body);
  return parsed.success ? parsed.data.error : {};
}

export function apiErrorCode(body: unknown): string | undefined {
  return parseApiError(body).code;
}

const statusMessages: Record<number, string> = {
  400: "The request could not be accepted. Check the values and try again.",
  401: "Your session has ended. Sign in again to continue.",
  403: "Your account cannot perform this action.",
  404: "This record is unavailable or you no longer have access to it.",
  409: "This record changed since you loaded it. Refresh and try again.",
  413: "The request is too large.",
  429: "Too many attempts. Please wait before trying again.",
};

/**
 * A user-facing message for a failed API call: the server's message when it
 * sent one, otherwise the caller's fallback, otherwise a message for the status.
 */
export function apiErrorMessage(error: unknown, status: number, fallback?: string): string {
  const message = parseApiError(error).message?.trim();
  if (message) return message;
  if (fallback) return fallback;
  if (status >= 500) return "The service is temporarily unavailable. Please try again.";
  return statusMessages[status] ?? "The request failed. Please try again.";
}

export const UNAUTHORIZED_MESSAGE = "Unauthorized";

export function unauthorizedError(): Error {
  return new Error(UNAUTHORIZED_MESSAGE);
}

export function isUnauthorizedError(error: unknown): boolean {
  return error instanceof Error && error.message === UNAUTHORIZED_MESSAGE;
}

export function isUnauthorizedStatus(status: number): boolean {
  return status === 401 || status === 403;
}

/**
 * Minutes to wait according to a Retry-After header, which may be delta-seconds
 * or an HTTP date. Absent or unparseable headers use the fallback.
 */
export function retryAfterMinutes(header: string | null | undefined, fallbackMinutes = 15, now = Date.now()): number {
  if (!header) return fallbackMinutes;
  const value = header.trim();
  let seconds: number;
  if (/^\d+$/.test(value)) {
    seconds = Number(value);
  } else {
    const at = Date.parse(value);
    if (Number.isNaN(at)) return fallbackMinutes;
    seconds = (at - now) / 1000;
  }
  if (!Number.isFinite(seconds)) return fallbackMinutes;
  return Math.max(1, Math.ceil(seconds / 60));
}

export function waitMessage(minutes: number): string {
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}
