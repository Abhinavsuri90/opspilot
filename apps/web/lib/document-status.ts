const IN_PROGRESS = new Set(["queued", "extracting", "validating"]);
const COMPLETED = new Set(["approved", "auto_approved"]);

const labels: Record<string, string> = {
  queued: "Queued",
  extracting: "Extracting",
  validating: "Validating",
  needs_review: "Needs review",
  approved: "Approved",
  auto_approved: "Auto-approved",
  rejected: "Rejected",
  failed: "Failed",
};

export type DocumentStatusTone = "progress" | "review" | "completed" | "rejected" | "failed" | "neutral";

export function isDocumentInProgress(status: string): boolean {
  return IN_PROGRESS.has(status);
}

/** Approved by a person or by policy: nothing further happens to the document. */
export function isDocumentCompleted(status: string): boolean {
  return COMPLETED.has(status);
}

export function documentStatusLabel(status: string): string {
  return labels[status] ?? status.replaceAll("_", " ");
}

export function documentStatusTone(status: string): DocumentStatusTone {
  if (isDocumentInProgress(status)) return "progress";
  if (status === "needs_review") return "review";
  if (status === "failed") return "failed";
  if (isDocumentCompleted(status)) return "completed";
  if (status === "rejected") return "rejected";
  return "neutral";
}

/** Sums every in-progress bucket of a `status_counts` map, including `validating`. */
export function countInProgress(statusCounts: Record<string, number> | undefined): number {
  if (!statusCounts) return 0;
  return Object.entries(statusCounts).reduce((total, [status, count]) => total + (isDocumentInProgress(status) ? count : 0), 0);
}
