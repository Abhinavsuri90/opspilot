// The multi-file upload queue: files are validated and sent one at a time, and
// every file reports where it ended up. Pure so the page can be thin and the
// transitions testable. The File objects live outside the state.

import { validatePdfSelection } from "@/lib/upload";

export type UploadStatus = "queued" | "uploading" | "accepted" | "duplicate" | "failed";

export type UploadItem = {
  id: string;
  name: string;
  size: number;
  status: UploadStatus;
  /** Why the file failed, or what happened to it. */
  message: string | null;
  /** The document the API created or matched, once known. */
  documentId: string | null;
};

export type UploadQueueAction =
  | { type: "add"; files: { id: string; name: string; size: number }[] }
  | { type: "start"; id: string }
  | { type: "accepted"; id: string; documentId: string; duplicate: boolean }
  | { type: "failed"; id: string; message: string }
  | { type: "remove"; id: string }
  | { type: "clear-finished" };

const FINISHED: ReadonlySet<UploadStatus> = new Set(["accepted", "duplicate", "failed"]);

export function uploadQueueReducer(items: readonly UploadItem[], action: UploadQueueAction): UploadItem[] {
  switch (action.type) {
    case "add":
      return [...items, ...action.files.map(file => ({ id: file.id, name: file.name, size: file.size, status: "queued" as const, message: null, documentId: null }))];
    case "start":
      return items.map(item => item.id === action.id ? { ...item, status: "uploading", message: null, documentId: null } : item);
    case "accepted":
      return items.map(item => item.id === action.id ? { ...item, status: action.duplicate ? "duplicate" : "accepted", message: action.duplicate ? "Already in this workspace; its existing result is linked." : "Accepted; extraction is running.", documentId: action.documentId } : item);
    case "failed":
      return items.map(item => item.id === action.id ? { ...item, status: "failed", message: action.message, documentId: null } : item);
    case "remove":
      return items.filter(item => item.id !== action.id || item.status === "uploading");
    case "clear-finished":
      return items.filter(item => !FINISHED.has(item.status));
    default:
      return [...items];
  }
}

/** Files the next batch will send: never uploaded yet, or failed and worth another try. */
export function pendingUploads(items: readonly UploadItem[]): UploadItem[] {
  return items.filter(item => item.status === "queued" || item.status === "failed");
}

export function isUploading(items: readonly UploadItem[]): boolean {
  return items.some(item => item.status === "uploading");
}

/** The reason a file cannot be sent, checked right before its upload so an invalid pick fails loudly, not silently. */
export function uploadBlocker(file: Pick<File, "name" | "size">): string | null {
  return validatePdfSelection(file);
}

/** What the API's status code means to the person who dropped the file. */
export function uploadFailureMessage(status: number): string {
  if (status === 403) return "Your account cannot upload documents.";
  if (status === 409) return "This workspace cannot accept another document. Check its workflow configuration or document limit.";
  if (status === 429) return "Too many uploads in a short time. Wait a few minutes and try again.";
  if (status === 400 || status === 413 || status === 422) return "The PDF could not be accepted. Use a text-layer PDF smaller than 10 MB.";
  return "The upload service is temporarily unavailable. Please try again.";
}

export type BatchSummary = { status: string | null; alert: string | null };

/** One line for the batch that just finished: a status for what landed, an alert naming every file that did not. */
export function summarizeBatch(items: readonly UploadItem[]): BatchSummary {
  const accepted = items.filter(item => item.status === "accepted").length;
  const duplicates = items.filter(item => item.status === "duplicate");
  const failed = items.filter(item => item.status === "failed");
  const parts: string[] = [];
  if (accepted > 0) parts.push(`${accepted} ${accepted === 1 ? "document" : "documents"} uploaded. Track ${accepted === 1 ? "its" : "their"} status and review the results below.`);
  if (duplicates.length > 0) parts.push(duplicates.length === 1 ? `${duplicates[0].name} was already in this workspace; its existing result is open below.` : `${duplicates.length} files were already in this workspace and were not uploaded again.`);
  return {
    status: parts.length > 0 ? parts.join(" ") : null,
    alert: failed.length > 0 ? failed.map(item => `${item.name}: ${item.message ?? "The upload failed."}`).join(" · ") : null,
  };
}

export const uploadStatusLabels: Record<UploadStatus, string> = {
  queued: "Queued",
  uploading: "Uploading",
  accepted: "Accepted",
  duplicate: "Duplicate",
  failed: "Failed",
};
