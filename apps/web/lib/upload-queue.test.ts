import { describe, expect, it } from "vitest";
import { isUploading, pendingUploads, summarizeBatch, uploadBlocker, uploadFailureMessage, uploadQueueReducer, type UploadItem } from "./upload-queue";

const files = [
  { id: "a", name: "po.pdf", size: 900 },
  { id: "b", name: "note.txt", size: 12 },
  { id: "c", name: "dn.pdf", size: 800 },
];

describe("upload queue reducer", () => {
  it("queues added files and walks each one through its outcome", () => {
    let items = uploadQueueReducer([], { type: "add", files });
    expect(items.map(item => item.status)).toEqual(["queued", "queued", "queued"]);
    expect(pendingUploads(items).map(item => item.id)).toEqual(["a", "b", "c"]);

    items = uploadQueueReducer(items, { type: "start", id: "a" });
    expect(isUploading(items)).toBe(true);
    items = uploadQueueReducer(items, { type: "accepted", id: "a", documentId: "doc-1", duplicate: false });
    items = uploadQueueReducer(items, { type: "failed", id: "b", message: "Choose a PDF." });
    items = uploadQueueReducer(items, { type: "start", id: "c" });
    items = uploadQueueReducer(items, { type: "accepted", id: "c", documentId: "doc-2", duplicate: true });

    expect(isUploading(items)).toBe(false);
    expect(items.map(item => [item.status, item.documentId])).toEqual([["accepted", "doc-1"], ["failed", null], ["duplicate", "doc-2"]]);
    expect(items[1].message).toBe("Choose a PDF.");
    expect(items[2].message).toContain("Already in this workspace");
    // Failed files are offered again; accepted and duplicate ones are not.
    expect(pendingUploads(items).map(item => item.id)).toEqual(["b"]);
  });

  it("retries a failed file from a clean slate", () => {
    let items = uploadQueueReducer([], { type: "add", files: [files[0]] });
    items = uploadQueueReducer(items, { type: "failed", id: "a", message: "Unavailable." });
    items = uploadQueueReducer(items, { type: "start", id: "a" });
    expect(items[0]).toMatchObject({ status: "uploading", message: null, documentId: null });
  });

  it("removes queued or finished files but never one in flight, and clears finished ones", () => {
    let items = uploadQueueReducer([], { type: "add", files });
    items = uploadQueueReducer(items, { type: "start", id: "a" });
    items = uploadQueueReducer(items, { type: "remove", id: "a" });
    items = uploadQueueReducer(items, { type: "remove", id: "b" });
    expect(items.map(item => item.id)).toEqual(["a", "c"]);
    items = uploadQueueReducer(items, { type: "accepted", id: "a", documentId: "doc-1", duplicate: false });
    items = uploadQueueReducer(items, { type: "clear-finished" });
    expect(items.map(item => item.id)).toEqual(["c"]);
  });
});

describe("upload messages", () => {
  it("blocks non-PDF or empty files before they are sent", () => {
    expect(uploadBlocker({ name: "note.txt", size: 12 })).toContain("Choose a PDF");
    expect(uploadBlocker({ name: "po.pdf", size: 0 })).toContain("between 1 byte");
    expect(uploadBlocker({ name: "po.pdf", size: 900 })).toBeNull();
  });

  it("explains API failures by status", () => {
    expect(uploadFailureMessage(403)).toBe("Your account cannot upload documents.");
    expect(uploadFailureMessage(409)).toContain("cannot accept another document");
    expect(uploadFailureMessage(429)).toContain("Too many uploads");
    expect(uploadFailureMessage(400)).toContain("could not be accepted");
    expect(uploadFailureMessage(413)).toContain("could not be accepted");
    expect(uploadFailureMessage(503)).toContain("temporarily unavailable");
  });

  it("summarizes a batch as a status line for what landed and an alert for what did not", () => {
    const items: UploadItem[] = [
      { id: "a", name: "po.pdf", size: 1, status: "accepted", message: null, documentId: "d1" },
      { id: "b", name: "note.txt", size: 1, status: "failed", message: "Choose a PDF.", documentId: null },
      { id: "c", name: "dn.pdf", size: 1, status: "duplicate", message: null, documentId: "d2" },
    ];
    expect(summarizeBatch(items)).toEqual({
      status: "1 document uploaded. Track its status and review the results below. dn.pdf was already in this workspace; its existing result is open below.",
      alert: "note.txt: Choose a PDF.",
    });
    expect(summarizeBatch([items[1]])).toEqual({ status: null, alert: "note.txt: Choose a PDF." });
    expect(summarizeBatch([{ ...items[0], id: "x" }, items[0]]).status).toBe("2 documents uploaded. Track their status and review the results below.");
    expect(summarizeBatch([])).toEqual({ status: null, alert: null });
  });
});
