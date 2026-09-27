import type { components } from "@/lib/schema";

export type ActionSummary = components["schemas"]["ActionSummary"];
export type ActionDetail = components["schemas"]["ActionDetail"];
export type DiffResponse = components["schemas"]["DiffResponse"];

export type ActionTab = "pending" | "history" | "dead";
export type ActionTone = "review" | "progress" | "completed" | "rejected" | "failed" | "neutral";

export const ACTION_STATUSES = ["proposed", "approved", "executing", "retrying", "succeeded", "failed", "dead_lettered", "rejected", "shadowed", "forbidden"] as const;
export type ActionStatus = (typeof ACTION_STATUSES)[number];

/** Statuses that can appear in the History tab: everything that is no longer awaiting a human decision. */
export const HISTORY_STATUSES: readonly ActionStatus[] = ["approved", "executing", "retrying", "succeeded", "failed", "dead_lettered", "rejected", "shadowed", "forbidden"];
/** Statuses that can be retried: the worker gave up, or the last attempt failed and no retry is scheduled. */
export const RETRYABLE_STATUSES: ReadonlySet<string> = new Set(["dead_lettered", "failed"]);
/** The list is polled; anything that a worker may still change deserves a fresh look. */
export const ACTIONS_POLL_MS = 10_000;
/** The API caps a page at 100; a count that fills the page is shown as "100+". */
export const ACTION_COUNT_LIMIT = 100;

const labels: Record<string, string> = {
  proposed: "Awaiting approval",
  approved: "Approved · queued",
  executing: "Executing",
  retrying: "Retrying",
  succeeded: "Succeeded",
  failed: "Failed",
  dead_lettered: "Dead letter",
  rejected: "Rejected",
  shadowed: "Shadowed",
  forbidden: "Forbidden",
};

const policyLabels: Record<string, string> = {
  auto: "Auto",
  needs_approval: "Needs approval",
  forbidden: "Forbidden",
};

export function actionStatusLabel(status: string): string {
  return labels[status] ?? status.replaceAll("_", " ");
}

export function actionStatusTone(status: string): ActionTone {
  switch (status) {
    case "proposed": return "review";
    case "approved":
    case "executing":
    case "retrying": return "progress";
    case "succeeded": return "completed";
    case "failed":
    case "dead_lettered": return "failed";
    case "rejected":
    case "forbidden": return "rejected";
    default: return "neutral";
  }
}

export function policyModeLabel(mode: string): string {
  return policyLabels[mode] ?? mode.replaceAll("_", " ");
}

export function actionTypeLabel(actionType: string): string {
  return actionType.replaceAll("_", " ");
}

export function tabForStatus(status: string): ActionTab {
  if (status === "proposed") return "pending";
  if (RETRYABLE_STATUSES.has(status)) return "dead";
  return "history";
}

export type ActionsQuery = { status?: string; document_id?: string; limit: number };

/**
 * The API filters by one status at a time, so a tab is one or more list calls:
 * Pending is the proposals, Dead letters merges dead-lettered and failed actions,
 * and History without a filter fetches everything and hides proposals client-side.
 */
export function tabQueries(tab: ActionTab, options: { statusFilter?: string; documentId?: string } = {}): ActionsQuery[] {
  const document_id = options.documentId?.trim() || undefined;
  if (tab === "pending") return [{ status: "proposed", document_id, limit: ACTION_COUNT_LIMIT }];
  if (tab === "dead") return [{ status: "dead_lettered", document_id, limit: ACTION_COUNT_LIMIT }, { status: "failed", document_id, limit: ACTION_COUNT_LIMIT }];
  const status = options.statusFilter && HISTORY_STATUSES.includes(options.statusFilter as ActionStatus) ? options.statusFilter : undefined;
  return [{ status, document_id, limit: ACTION_COUNT_LIMIT }];
}

/** The rows a tab shows out of what the API returned, newest first, without duplicates across merged pages. */
export function rowsForTab(tab: ActionTab, pages: ActionSummary[][]): ActionSummary[] {
  const seen = new Set<string>();
  const rows: ActionSummary[] = [];
  for (const page of pages) {
    for (const action of page) {
      if (seen.has(action.id)) continue;
      if (tab === "pending" && action.status !== "proposed") continue;
      if (tab === "history" && action.status === "proposed") continue;
      if (tab === "dead" && !RETRYABLE_STATUSES.has(action.status)) continue;
      seen.add(action.id);
      rows.push(action);
    }
  }
  return rows.sort((a, b) => b.proposed_at.localeCompare(a.proposed_at) || b.id.localeCompare(a.id));
}

/** "100+" once a count fills the page the API can return; the API has no total. */
export function formatActionCount(count: number | undefined, limit = ACTION_COUNT_LIMIT): string {
  if (count === undefined) return "—";
  return count >= limit ? `${limit}+` : String(count);
}

export type DecisionBody = components["schemas"]["ActionDecisionRequest"];

/** The decision request, or the reason it cannot be sent yet. Rejections carry a reason; approvals send an empty comment. */
export function decisionBody(action: Pick<ActionSummary, "version" | "status">, decision: "approve" | "reject", comment: string): { body: DecisionBody } | { error: string } {
  if (action.status !== "proposed") return { error: "Only actions awaiting approval can be decided." };
  const trimmed = comment.trim();
  if (decision === "reject" && !trimmed) return { error: "Explain why this action is rejected." };
  if (trimmed.length > 4000) return { error: "Keep the note under 4000 characters." };
  return { body: { version: action.version, decision, comment: trimmed } };
}

export type DiffRow = { key: string; before: string | null; after: string; changed: boolean };

export function formatDiffValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (value === "") return "(empty)";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The preview's keys, with one level of nested objects flattened to `parent.child`
 * so a webhook envelope reads as `payload.vendor` rather than a JSON blob.
 */
function flatten(record: Record<string, unknown> | null | undefined): Map<string, unknown> {
  const flat = new Map<string, unknown>();
  for (const [key, value] of Object.entries(record ?? {})) {
    if (isPlainObject(value) && Object.keys(value).length > 0) {
      for (const [child, nested] of Object.entries(value)) flat.set(`${key}.${child}`, nested);
    } else {
      flat.set(key, value);
    }
  }
  return flat;
}

/**
 * One row per key of the preview. With a `before` snapshot the table marks what
 * changes; without one every row is new, so nothing is marked.
 */
export function diffRows(preview: Pick<DiffResponse, "before" | "after">): DiffRow[] {
  const after = flatten(preview.after);
  const before = preview.before ? flatten(preview.before) : null;
  const keys = [...after.keys()];
  for (const key of before?.keys() ?? []) if (!keys.includes(key)) keys.push(key);
  return keys.map(key => {
    const afterValue = after.has(key) ? formatDiffValue(after.get(key)) : "—";
    const beforeValue = before ? (before.has(key) ? formatDiffValue(before.get(key)) : "—") : null;
    return { key, before: beforeValue, after: afterValue, changed: beforeValue !== null && beforeValue !== afterValue };
  });
}
