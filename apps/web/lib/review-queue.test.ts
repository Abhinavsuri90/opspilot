import { describe, expect, it } from "vitest";
import { buildQueueQuery, DEFAULT_QUEUE_FILTERS, formatQueueTotal, formatSla, formatSpan, queueFiltersActive } from "./review-queue";

describe("queue query parameters", () => {
  it("sends only the page window for the default filters", () => {
    expect(buildQueueQuery(DEFAULT_QUEUE_FILTERS)).toEqual({ offset: 0, limit: 25 });
    expect(buildQueueQuery(DEFAULT_QUEUE_FILTERS, 50)).toEqual({ offset: 50, limit: 25 });
    expect(buildQueueQuery(DEFAULT_QUEUE_FILTERS, -10).offset).toBe(0);
  });

  it("maps every filter to its API parameter", () => {
    expect(buildQueueQuery({ documentType: " invoice ", vendor: " Northwind ", age: "4", assigned: "me" }, 25)).toEqual({
      document_type: "invoice", vendor: "Northwind", max_age_hours: 4, assigned: "me", offset: 25, limit: 25,
    });
    expect(buildQueueQuery({ ...DEFAULT_QUEUE_FILTERS, assigned: "unassigned", age: "24" })).toMatchObject({ assigned: "unassigned", max_age_hours: 24 });
    expect(buildQueueQuery({ ...DEFAULT_QUEUE_FILTERS, vendor: "   " })).not.toHaveProperty("vendor");
    expect(buildQueueQuery({ ...DEFAULT_QUEUE_FILTERS, vendor: "x".repeat(300) }).vendor).toHaveLength(200);
  });

  it("knows when any filter, including the client-side overdue toggle, is active", () => {
    expect(queueFiltersActive(DEFAULT_QUEUE_FILTERS)).toBe(false);
    expect(queueFiltersActive(DEFAULT_QUEUE_FILTERS, true)).toBe(true);
    expect(queueFiltersActive({ ...DEFAULT_QUEUE_FILTERS, vendor: "a" })).toBe(true);
    expect(queueFiltersActive({ ...DEFAULT_QUEUE_FILTERS, age: "1" })).toBe(true);
    expect(queueFiltersActive({ ...DEFAULT_QUEUE_FILTERS, assigned: "me" })).toBe(true);
    expect(queueFiltersActive({ ...DEFAULT_QUEUE_FILTERS, documentType: "invoice" })).toBe(true);
  });
});

describe("SLA formatting", () => {
  const now = Date.parse("2026-09-27T12:00:00Z");

  it("counts down to the deadline", () => {
    expect(formatSla("2026-09-27T15:58:00Z", now)).toEqual({ label: "Due in 3h 58m", overdue: false, known: true });
    expect(formatSla("2026-09-27T12:42:00Z", now)).toEqual({ label: "Due in 42m", overdue: false, known: true });
    expect(formatSla("2026-09-27T14:00:00Z", now).label).toBe("Due in 2h");
    expect(formatSla("2026-09-29T15:00:00Z", now).label).toBe("Due in 2d 3h");
    expect(formatSla("2026-09-27T12:00:20Z", now).label).toBe("Due in <1m");
  });

  it("reports how far past the deadline a task is", () => {
    expect(formatSla("2026-09-27T10:55:00Z", now)).toEqual({ label: "Overdue by 1h 5m", overdue: true, known: true });
    expect(formatSla("2026-09-27T11:48:00Z", now).label).toBe("Overdue by 12m");
    expect(formatSla("2026-09-24T12:00:00Z", now).label).toBe("Overdue by 3d");
  });

  it("handles a missing or unreadable deadline", () => {
    expect(formatSla(null, now)).toEqual({ label: "No SLA", overdue: false, known: false });
    expect(formatSla("not a date", now).known).toBe(false);
  });

  it("formats spans without empty parts", () => {
    expect(formatSpan(0)).toBe("<1m");
    expect(formatSpan(3 * 60 * 60 * 1000)).toBe("3h");
    expect(formatSpan(26 * 60 * 60 * 1000)).toBe("1d 2h");
  });
});

describe("queue totals", () => {
  it("shows the amount with its currency and tolerates raw extracted text", () => {
    expect(formatQueueTotal("1234.5", "USD")).toBe("1,234.50 USD");
    expect(formatQueueTotal("$123.45", "USD")).toBe("123.45 USD");
    expect(formatQueueTotal("123.45", null)).toBe("123.45");
    expect(formatQueueTotal(null, "USD")).toBe("—");
    expect(formatQueueTotal("twelve", "EUR")).toBe("twelve EUR");
  });
});
