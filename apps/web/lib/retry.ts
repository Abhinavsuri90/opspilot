export type RetryFailure = {
  message: string;
  limitReached: boolean;
  refreshDocument: boolean;
};

function errorCode(body: unknown): string | undefined {
  if (!body || typeof body !== "object" || !("error" in body)) return undefined;
  const detail = body.error;
  if (!detail || typeof detail !== "object" || !("code" in detail)) return undefined;
  return typeof detail.code === "string" ? detail.code : undefined;
}

export function classifyRetryFailure(status: number, body: unknown): RetryFailure {
  if (status === 403) {
    return { message: "Your account cannot retry this invoice.", limitReached: false, refreshDocument: false };
  }
  if (status === 409 && errorCode(body) === "retry_limit_reached") {
    return {
      message: "This invoice has reached its limit of two manual retries. Further retries are disabled.",
      limitReached: true,
      refreshDocument: false,
    };
  }
  if (status === 409) {
    return {
      message: "This invoice is no longer failed. Its status will refresh shortly.",
      limitReached: false,
      refreshDocument: true,
    };
  }
  return {
    message: "The retry service is temporarily unavailable. Please try again.",
    limitReached: false,
    refreshDocument: false,
  };
}
