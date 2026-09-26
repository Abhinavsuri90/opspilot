import { describe, expect, it } from "vitest";
import { isDocumentInProgress } from "./document-status";

describe("document polling states", () => {
  it("keeps polling while the worker owns or validates a document", () => {
    for (const status of ["queued", "extracting", "validating"]) {
      expect(isDocumentInProgress(status)).toBe(true);
    }
  });

  it("stops polling after extraction finishes or fails", () => {
    for (const status of ["needs_review", "failed"]) {
      expect(isDocumentInProgress(status)).toBe(false);
    }
  });
});
