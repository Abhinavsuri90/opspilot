import { z } from "zod";
import { parseApiError } from "@/lib/errors";
import type { components } from "@/lib/schema";

export type WorkflowResponse = components["schemas"]["WorkflowResponse"];
export type WorkflowUpdate = components["schemas"]["WorkflowUpdate"];
export type ReviewPolicy = "always" | "threshold";

export const MAX_WORKFLOW_YAML_BYTES = 64 * 1024;
export const SLA_MINUTES = { min: 1, max: 60 * 24 * 30 } as const;
export const BASELINE_MINUTES = { min: 0, max: 60 * 24 } as const;

// The three scalars the form edits live at the top level of the document, so a
// line-level rewrite is exact: no YAML parser is needed in the browser and the
// administrator's formatting and comments elsewhere survive untouched.
const TOP_LEVEL_KEY = /^([A-Za-z_][A-Za-z0-9_]*):(.*)$/;

function unquote(value: string): string {
  const trimmed = value.replace(/\s+#.*$/, "").trim();
  if (trimmed.length >= 2 && ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'")))) return trimmed.slice(1, -1);
  return trimmed;
}

/** The raw scalar after `key:` on a top-level line, or null when the key is absent or not a scalar. */
export function readTopLevelScalar(yaml: string, key: string): string | null {
  for (const line of yaml.split("\n")) {
    const match = TOP_LEVEL_KEY.exec(line);
    if (!match || match[1] !== key) continue;
    const value = unquote(match[2]);
    return value === "" ? null : value;
  }
  return null;
}

/** Rewrite (or append) a top-level `key: value` line, keeping everything else byte for byte. */
export function setTopLevelScalar(yaml: string, key: string, value: string | number): string {
  const lines = yaml.split("\n");
  const index = lines.findIndex(line => { const match = TOP_LEVEL_KEY.exec(line); return match !== null && match[1] === key; });
  const rendered = `${key}: ${value}`;
  if (index >= 0) {
    lines[index] = rendered;
    return lines.join("\n");
  }
  const trimmed = yaml.replace(/\s+$/, "");
  return trimmed ? `${trimmed}\n${rendered}\n` : `${rendered}\n`;
}

export type WorkflowScalars = { review_policy: ReviewPolicy | null; review_sla_minutes: number | null; baseline_minutes: number | null };

function integerOrNull(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  return Number(value);
}

/** What the form controls show, read from the text the administrator is editing. */
export function workflowScalars(yaml: string): WorkflowScalars {
  const policy = readTopLevelScalar(yaml, "review_policy");
  return {
    review_policy: policy === "always" || policy === "threshold" ? policy : null,
    review_sla_minutes: integerOrNull(readTopLevelScalar(yaml, "review_sla_minutes")),
    baseline_minutes: integerOrNull(readTopLevelScalar(yaml, "baseline_minutes")),
  };
}

export function yamlByteLength(yaml: string): number {
  return new TextEncoder().encode(yaml).length;
}

export function workflowFilename(version: number): string {
  return `workflow-v${version}.yaml`;
}

/** Character range of a 1-based line, for selecting it in the editor. */
export function lineRange(yaml: string, line: number): { start: number; end: number } | null {
  const lines = yaml.split("\n");
  if (line < 1 || line > lines.length) return null;
  let start = 0;
  for (let index = 0; index < line - 1; index += 1) start += lines[index].length + 1;
  return { start, end: start + lines[line - 1].length };
}

export type WorkflowProblem = { field: string | null; message: string; line: number | null; column: number | null };
export type WorkflowFailure = { message: string; problems: WorkflowProblem[]; conflict: boolean };

const LINE_REFERENCE = /\(line (\d+), column (\d+)\)/;

function problemFrom(field: string | null, message: string): WorkflowProblem {
  const match = LINE_REFERENCE.exec(message);
  return { field, message, line: match ? Number(match[1]) : null, column: match ? Number(match[2]) : null };
}

/**
 * The API answers an invalid save with a 422 whose `details` list each failing
 * field (`document_types.0.fields.2.threshold`) or, for unparseable YAML, one
 * message carrying the line and column. A 409 means the version moved on.
 */
export function describeWorkflowFailure(body: unknown, status: number): WorkflowFailure {
  const parsed = parseApiError(body);
  const message = parsed.message?.trim() || (status === 409 ? "The workflow changed since you loaded it." : status === 413 ? "The YAML is too large." : "Could not save the workflow.");
  const problems = (parsed.details ?? []).filter(item => item.message?.trim()).map(item => problemFrom(item.field?.trim() || null, item.message!.trim()));
  if (problems.length === 0 && status === 422) problems.push(problemFrom(null, message));
  return { message, problems, conflict: status === 409 };
}

// The summary is read from the API's normalized config, so unknown keys pass through
// and a missing optional is simply absent from the summary rather than an error.
const fieldSchema = z.object({ name: z.string(), label: z.string().optional(), type: z.string().optional(), required: z.boolean().optional(), threshold: z.number().optional(), regex: z.string().nullish(), enum: z.array(z.string()).nullish() }).loose();
const ruleSchema = z.object({ name: z.string(), expression: z.string(), tolerance: z.union([z.number(), z.string()]).optional(), message: z.string().nullish() }).loose();
const documentTypeSchema = z.object({ name: z.string(), label: z.string().optional(), detect: z.array(z.string()).optional(), fields: z.array(fieldSchema).default([]), rules: z.array(ruleSchema).default([]) }).loose();
const destinationSchema = z.object({ name: z.string(), connector: z.string(), action_type: z.string(), mapping: z.record(z.string(), z.string()).default({}), enabled: z.boolean().default(true), document_types: z.array(z.string()).nullish() }).loose();
const workflowSummarySchema = z.object({
  document_types: z.array(documentTypeSchema).default([]),
  review_policy: z.string().optional(),
  review_sla_minutes: z.number().optional(),
  baseline_minutes: z.number().optional(),
  action_policies: z.record(z.string(), z.string()).default({}),
  destinations: z.array(destinationSchema).default([]),
}).loose();

export type WorkflowSummary = z.infer<typeof workflowSummarySchema>;

export function summarizeWorkflow(config: unknown): WorkflowSummary | null {
  const parsed = workflowSummarySchema.safeParse(config);
  return parsed.success ? parsed.data : null;
}
