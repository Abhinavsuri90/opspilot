import { describe, expect, it } from "vitest";
import { describeWorkflowFailure, lineRange, readTopLevelScalar, setTopLevelScalar, summarizeWorkflow, workflowScalars } from "./workflow";

const yaml = `document_types:
- name: invoice
  fields:
  - name: total
    threshold: 0.9
review_policy: always
review_sla_minutes: 240 # four hours
baseline_minutes: '12'
`;

describe("top-level scalars", () => {
  it("reads only top-level keys, ignoring nested ones, quotes and trailing comments", () => {
    expect(readTopLevelScalar(yaml, "review_policy")).toBe("always");
    expect(readTopLevelScalar(yaml, "review_sla_minutes")).toBe("240");
    expect(readTopLevelScalar(yaml, "baseline_minutes")).toBe("12");
    expect(readTopLevelScalar(yaml, "threshold")).toBeNull();
    expect(readTopLevelScalar(yaml, "missing")).toBeNull();
    expect(workflowScalars(yaml)).toEqual({ review_policy: "always", review_sla_minutes: 240, baseline_minutes: 12 });
    expect(workflowScalars("review_policy: sometimes\nreview_sla_minutes: soon\n")).toEqual({ review_policy: null, review_sla_minutes: null, baseline_minutes: null });
  });

  it("rewrites a key in place and appends a missing one without touching other lines", () => {
    const edited = setTopLevelScalar(yaml, "review_policy", "threshold");
    expect(edited).toContain("review_policy: threshold\n");
    expect(edited.split("\n").length).toBe(yaml.split("\n").length);
    expect(edited).toContain("    threshold: 0.9");
    const appended = setTopLevelScalar("document_types: []", "baseline_minutes", 30);
    expect(appended).toBe("document_types: []\nbaseline_minutes: 30\n");
    expect(setTopLevelScalar("", "review_sla_minutes", 5)).toBe("review_sla_minutes: 5\n");
  });

  it("maps a 1-based line to its character range", () => {
    expect(lineRange("a\nbb\nccc", 2)).toEqual({ start: 2, end: 4 });
    expect(lineRange("a\nbb\nccc", 3)).toEqual({ start: 5, end: 8 });
    expect(lineRange("a\nbb", 3)).toBeNull();
  });
});

describe("save failures", () => {
  it("turns field details into problems and extracts the line from a YAML parse error", () => {
    const invalid = describeWorkflowFailure({ error: { code: "validation_error", message: "Workflow configuration is invalid", details: [{ field: "document_types.0.fields.1.threshold", message: "Input should be less than or equal to 1" }] } }, 422);
    expect(invalid.conflict).toBe(false);
    expect(invalid.problems).toEqual([{ field: "document_types.0.fields.1.threshold", message: "Input should be less than or equal to 1", line: null, column: null }]);
    const unparseable = describeWorkflowFailure({ error: { code: "validation_error", message: "YAML could not be parsed: mapping values are not allowed here (line 7, column 12)", details: null } }, 422);
    expect(unparseable.problems).toEqual([{ field: null, message: expect.stringContaining("line 7"), line: 7, column: 12 }]);
  });

  it("flags a stale base version as a conflict", () => {
    const conflict = describeWorkflowFailure({ error: { code: "conflict", message: "Workflow configuration is at version 3; refresh and reapply your edit" } }, 409);
    expect(conflict).toMatchObject({ conflict: true, message: expect.stringContaining("version 3"), problems: [] });
  });
});

describe("structured summary", () => {
  it("reads document types, fields, rules and destinations from the saved config", () => {
    const summary = summarizeWorkflow({
      document_types: [{ name: "invoice", label: "Invoice", fields: [{ name: "vendor", type: "text", required: true, threshold: 0.8 }], rules: [{ name: "totals_add_up", expression: "subtotal + tax == total" }] }],
      review_policy: "always", review_sla_minutes: 240, baseline_minutes: 12, action_policies: { post_webhook: "auto" },
      destinations: [{ name: "notify", connector: "Receiver", action_type: "post_webhook", mapping: { vendor: "vendor" } }],
      future_key: true,
    });
    expect(summary?.document_types[0].fields[0]).toMatchObject({ name: "vendor", required: true, threshold: 0.8 });
    expect(summary?.destinations[0]).toMatchObject({ name: "notify", enabled: true, mapping: { vendor: "vendor" } });
    expect(summary?.action_policies).toEqual({ post_webhook: "auto" });
    expect(summarizeWorkflow("not a config")).toBeNull();
  });
});
