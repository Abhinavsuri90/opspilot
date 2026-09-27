import type { components } from "@/lib/schema";

export type FieldDetail = components["schemas"]["FieldDetail"];

export type FieldStatusSummary = { flagged: number; auto: number; corrected: number; accepted: number };

/** How many fields still need a person, were accepted by policy, were edited, or were accepted by a reviewer. */
export function summarizeFieldStatuses(fields: Pick<FieldDetail, "status">[]): FieldStatusSummary {
  const summary: FieldStatusSummary = { flagged: 0, auto: 0, corrected: 0, accepted: 0 };
  for (const field of fields) {
    if (field.status === "needs_review") summary.flagged += 1;
    else if (field.status === "auto") summary.auto += 1;
    else if (field.status === "corrected") summary.corrected += 1;
    else summary.accepted += 1;
  }
  return summary;
}

/** A value the browser's date input accepts, or empty when the extracted text is in another format. */
export function dateInputValue(value: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(value.trim()) ? value.trim() : "";
}

export function fieldInputKind(fieldType: string): "date" | "decimal" | "integer" | "text" {
  if (fieldType === "date") return "date";
  if (fieldType === "money") return "decimal";
  if (fieldType === "integer") return "integer";
  return "text";
}
