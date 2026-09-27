import { describe, expect, it } from "vitest";
import { actionStatusLabel, actionStatusTone, decisionBody, diffRows, formatActionCount, rowsForTab, tabForStatus, tabQueries, type ActionSummary } from "./actions";

function action(overrides: Partial<ActionSummary>): ActionSummary {
  return {
    id: "a1", document_id: "d1", filename: "invoice.pdf", destination: "notify", action_type: "post_webhook", connector_id: "c1", connector_name: "Receiver",
    status: "proposed", policy_mode: "needs_approval", preview: { kind: "post_webhook", title: "POST https://example.test", before: null, after: {}, lines: [] },
    attempts: 0, next_attempt_at: null, error: null, proposed_at: "2026-09-27T10:00:00Z", decided_by_email: null, decided_at: null, decision_comment: "", executed_at: null, version: 0,
    ...overrides,
  };
}

describe("action tabs", () => {
  it("asks the API for one status per call and merges dead letters with failed actions", () => {
    expect(tabQueries("pending")).toEqual([{ status: "proposed", document_id: undefined, limit: 100 }]);
    expect(tabQueries("dead", { documentId: " d1 " }).map(query => [query.status, query.document_id])).toEqual([["dead_lettered", "d1"], ["failed", "d1"]]);
    expect(tabQueries("history")).toEqual([{ status: undefined, document_id: undefined, limit: 100 }]);
    expect(tabQueries("history", { statusFilter: "shadowed" })[0].status).toBe("shadowed");
    expect(tabQueries("history", { statusFilter: "proposed" })[0].status).toBeUndefined();
  });

  it("keeps only the rows that belong to a tab, newest first, without duplicates", () => {
    const pages = [
      [action({ id: "a1", status: "proposed", proposed_at: "2026-09-27T10:00:00Z" }), action({ id: "a2", status: "succeeded", proposed_at: "2026-09-27T11:00:00Z" })],
      [action({ id: "a2", status: "succeeded", proposed_at: "2026-09-27T11:00:00Z" }), action({ id: "a3", status: "dead_lettered", proposed_at: "2026-09-27T12:00:00Z" })],
    ];
    expect(rowsForTab("pending", pages).map(row => row.id)).toEqual(["a1"]);
    expect(rowsForTab("history", pages).map(row => row.id)).toEqual(["a3", "a2"]);
    expect(rowsForTab("dead", pages).map(row => row.id)).toEqual(["a3"]);
    expect(tabForStatus("failed")).toBe("dead");
    expect(tabForStatus("approved")).toBe("history");
    expect(tabForStatus("proposed")).toBe("pending");
  });

  it("labels and tones every status, and caps counts at the page size", () => {
    expect(actionStatusLabel("dead_lettered")).toBe("Dead letter");
    expect(actionStatusLabel("approved")).toBe("Approved · queued");
    expect(actionStatusLabel("something_else")).toBe("something else");
    expect(actionStatusTone("proposed")).toBe("review");
    expect(actionStatusTone("executing")).toBe("progress");
    expect(actionStatusTone("succeeded")).toBe("completed");
    expect(actionStatusTone("dead_lettered")).toBe("failed");
    expect(actionStatusTone("forbidden")).toBe("rejected");
    expect(actionStatusTone("shadowed")).toBe("neutral");
    expect(formatActionCount(undefined)).toBe("—");
    expect(formatActionCount(7)).toBe("7");
    expect(formatActionCount(100)).toBe("100+");
  });
});

describe("decision payloads", () => {
  it("sends the version the card was rendered from and requires a reason to reject", () => {
    expect(decisionBody(action({ version: 3 }), "approve", "  ")).toEqual({ body: { version: 3, decision: "approve", comment: "" } });
    expect(decisionBody(action({ version: 3 }), "reject", "")).toEqual({ error: "Explain why this action is rejected." });
    expect(decisionBody(action({ version: 3 }), "reject", " wrong vendor ")).toEqual({ body: { version: 3, decision: "reject", comment: "wrong vendor" } });
    expect(decisionBody(action({ status: "approved" }), "approve", "")).toEqual({ error: "Only actions awaiting approval can be decided." });
  });
});

describe("diff rows", () => {
  it("lists new values without a before column when there is no prior state", () => {
    const rows = diffRows({ before: null, after: { vendor: "Northwind", total: "123.45", note: "" } });
    expect(rows).toEqual([
      { key: "vendor", before: null, after: "Northwind", changed: false },
      { key: "total", before: null, after: "123.45", changed: false },
      { key: "note", before: null, after: "(empty)", changed: false },
    ]);
  });

  it("marks changed and removed keys against a before snapshot", () => {
    const rows = diffRows({ before: { vendor: "Old Co", total: "1.00", legacy: true }, after: { vendor: "Old Co", total: "2.00", tags: ["a", "b"] } });
    expect(rows.find(row => row.key === "vendor")).toMatchObject({ before: "Old Co", after: "Old Co", changed: false });
    expect(rows.find(row => row.key === "total")).toMatchObject({ before: "1.00", after: "2.00", changed: true });
    expect(rows.find(row => row.key === "legacy")).toMatchObject({ before: "true", after: "—", changed: true });
    expect(rows.find(row => row.key === "tags")?.after).toBe(JSON.stringify(["a", "b"], null, 2));
  });

  it("flattens one level of nested objects so a webhook envelope reads field by field", () => {
    const rows = diffRows({ before: null, after: { action_type: "post_webhook", payload: { vendor: "Northwind Traders", total: "123.45" }, empty: {}, deep: { inner: { x: 1 } } } });
    expect(rows.map(row => row.key)).toEqual(["action_type", "payload.vendor", "payload.total", "empty", "deep.inner"]);
    expect(rows.find(row => row.key === "payload.vendor")?.after).toBe("Northwind Traders");
    expect(rows.find(row => row.key === "empty")?.after).toBe("{}");
    expect(rows.find(row => row.key === "deep.inner")?.after).toBe(JSON.stringify({ x: 1 }, null, 2));
  });
});
