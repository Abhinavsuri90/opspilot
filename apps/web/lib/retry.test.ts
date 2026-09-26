import { describe, expect, it } from "vitest";
import { classifyRetryFailure } from "./retry";

describe("retry error mapping", () => {
  it("distinguishes the exhausted retry limit from other conflicts", () => {
    const exhausted = classifyRetryFailure(409, {
      error: { code: "retry_limit_reached", message: "Manual retry limit reached for this document" },
    });
    expect(exhausted.limitReached).toBe(true);
    expect(exhausted.message).toContain("two manual retries");
    expect(exhausted.refreshDocument).toBe(false);

    const conflict = classifyRetryFailure(409, { error: { code: "request_failed" } });
    expect(conflict.limitReached).toBe(false);
    expect(conflict.refreshDocument).toBe(true);
  });

  it("keeps permission and transient failures actionable", () => {
    expect(classifyRetryFailure(403, null).message).toContain("cannot retry");
    expect(classifyRetryFailure(503, null).message).toContain("try again");
  });
});
