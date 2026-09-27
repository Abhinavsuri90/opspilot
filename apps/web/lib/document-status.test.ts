import { describe, expect, it } from "vitest";
import { countInProgress, documentStatusLabel, documentStatusTone, isDocumentCompleted, isDocumentInProgress } from "./document-status";

describe("document polling states", () => {
  it("keeps polling while the worker owns or validates a document", () => {
    for (const status of ["queued", "extracting", "validating"]) {
      expect(isDocumentInProgress(status)).toBe(true);
    }
  });

  it("stops polling after extraction finishes or fails", () => {
    for (const status of ["needs_review", "failed", "approved", "auto_approved", "rejected"]) {
      expect(isDocumentInProgress(status)).toBe(false);
    }
  });

  it("counts every in-progress bucket of a summary, including validating", () => {
    expect(countInProgress({ queued: 1, extracting: 2, validating: 3, needs_review: 4, failed: 5 })).toBe(6);
    expect(countInProgress(undefined)).toBe(0);
  });
});

describe("document status presentation", () => {
  it("labels every workflow status for people", () => {
    expect(documentStatusLabel("validating")).toBe("Validating");
    expect(documentStatusLabel("auto_approved")).toBe("Auto-approved");
    expect(documentStatusLabel("needs_review")).toBe("Needs review");
    expect(documentStatusLabel("queued")).toBe("Queued");
    expect(documentStatusLabel("some_new_state")).toBe("some new state");
  });

  it("treats policy approval like human approval", () => {
    expect(isDocumentCompleted("auto_approved")).toBe(true);
    expect(isDocumentCompleted("approved")).toBe(true);
    expect(isDocumentCompleted("needs_review")).toBe(false);
    expect(documentStatusTone("auto_approved")).toBe("completed");
    expect(documentStatusTone("approved")).toBe("completed");
    expect(documentStatusTone("validating")).toBe("progress");
    expect(documentStatusTone("needs_review")).toBe("review");
    expect(documentStatusTone("failed")).toBe("failed");
    expect(documentStatusTone("rejected")).toBe("rejected");
    expect(documentStatusTone("unknown")).toBe("neutral");
  });
});
