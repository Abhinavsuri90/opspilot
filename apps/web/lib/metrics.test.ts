import { describe, expect, it } from "vitest";
import { COST_NOT_TRACKED, EMPTY_VALUE, formatCost, formatCount, formatDay, formatHours, formatMinutes, formatRate, isMetricRange, kpiDefinitions, kpiTiles, seriesRows, toggleSeries, type MetricsOverview } from "./metrics";

const overview: MetricsOverview = {
  range: { days: 30, start: "2026-08-29", end: "2026-09-27", document_type: null },
  documents_processed: 1284,
  auto_approve_rate: 0.8251,
  field_accuracy: 0.9,
  median_time_to_complete_minutes: 65.4,
  review_queue_depth: 7,
  cost_per_document: null,
  hours_saved: 240.75,
  baseline_minutes: 12,
  series: [
    { day: "2026-09-27", documents: 3, auto_approved: 1, needs_review: 2, corrected_fields: 1, total_fields: 20, completed: 1, review_minutes: 14.5 },
    { day: "2026-09-26", documents: 5, auto_approved: 4, needs_review: 1, corrected_fields: 0, total_fields: 30, completed: 0, review_minutes: 0 },
  ],
};

describe("KPI formatting", () => {
  it("formats rates as percentages with at most one decimal", () => {
    expect(formatRate(0.8251)).toBe("82.5%");
    expect(formatRate(1)).toBe("100%");
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(1.4)).toBe("100%");
    expect(formatRate(null)).toBe(EMPTY_VALUE);
    expect(formatRate(undefined)).toBe(EMPTY_VALUE);
    expect(formatRate(Number.NaN)).toBe(EMPTY_VALUE);
  });

  it("formats minutes the way people say them", () => {
    expect(formatMinutes(0)).toBe("0 min");
    expect(formatMinutes(0.4)).toBe("<1 min");
    expect(formatMinutes(12.4)).toBe("12 min");
    expect(formatMinutes(65.4)).toBe("1 h 5 min");
    expect(formatMinutes(120)).toBe("2 h");
    expect(formatMinutes(-3)).toBe("0 min");
    expect(formatMinutes(null)).toBe(EMPTY_VALUE);
  });

  it("formats hours saved and counts, never negative", () => {
    expect(formatHours(0)).toBe("0 h");
    expect(formatHours(1.25)).toBe("1.3 h");
    expect(formatHours(12)).toBe("12 h");
    expect(formatHours(1234.6)).toBe("1,235 h");
    expect(formatHours(-2)).toBe("0 h");
    expect(formatCount(1284)).toBe("1,284");
    expect(formatCount(null)).toBe(EMPTY_VALUE);
  });

  it("says cost is not tracked until the API reports a number", () => {
    expect(formatCost(null)).toBe(COST_NOT_TRACKED);
    expect(formatCost(undefined)).toBe(COST_NOT_TRACKED);
    expect(formatCost(0.0123)).toBe("0.012");
    expect(formatCost(2.5)).toBe("2.50");
  });

  it("only accepts the three supported ranges", () => {
    expect(isMetricRange(7)).toBe(true);
    expect(isMetricRange(30)).toBe(true);
    expect(isMetricRange(90)).toBe(true);
    expect(isMetricRange(14)).toBe(false);
  });
});

describe("KPI tiles", () => {
  it("builds the seven tiles from an overview", () => {
    const tiles = kpiTiles(overview);
    expect(tiles.map(tile => tile.id)).toEqual(["documents_processed", "auto_approve_rate", "field_accuracy", "median_time_to_complete", "review_queue_depth", "cost_per_document", "hours_saved"]);
    expect(tiles.map(tile => tile.value)).toEqual(["1,284", "82.5%", "90%", "1 h 5 min", "7", COST_NOT_TRACKED, "241 h"]);
    expect(tiles[0].detail).toBe("Reached a decision path in the last 30 days");
    expect(tiles[6].detail).toBe("Against a 12-minute manual baseline per document");
    expect(tiles[5].empty).toBe(true);
    expect(tiles[1].empty).toBe(false);
    expect(kpiDefinitions().map(item => item.id)).toEqual(tiles.map(tile => tile.id));
  });

  it("shows dashes and quiet details while nothing is measured", () => {
    const tiles = kpiTiles({ ...overview, documents_processed: 0, auto_approve_rate: null, field_accuracy: null, median_time_to_complete_minutes: null, hours_saved: 0 });
    expect(tiles.map(tile => tile.value)).toEqual(["0", EMPTY_VALUE, EMPTY_VALUE, EMPTY_VALUE, "7", COST_NOT_TRACKED, "0 h"]);
    expect(tiles[1].detail).toBe("No processed documents yet");
    expect(tiles[2].detail).toBe("No fields assessed yet");
    expect(tiles[3].detail).toBe("No completed reviews yet");
    expect(tiles.filter(tile => tile.empty).map(tile => tile.id)).toEqual(["auto_approve_rate", "field_accuracy", "median_time_to_complete", "cost_per_document"]);
  });

  it("renders every value as a dash before the overview loads", () => {
    const tiles = kpiTiles(undefined);
    expect(tiles).toHaveLength(7);
    expect(tiles.every(tile => tile.value === EMPTY_VALUE && tile.empty)).toBe(true);
    expect(tiles[0].detail).toBe("Reached a decision path in the selected range");
  });
});

describe("chart rows", () => {
  it("orders the series by day with a short label and the four plotted counts", () => {
    const rows = seriesRows(overview.series);
    expect(rows.map(row => row.day)).toEqual(["2026-09-26", "2026-09-27"]);
    expect(rows[0]).toEqual({ day: "2026-09-26", label: "Sep 26", documents: 5, needs_review: 1, auto_approved: 4, completed: 0 });
    expect(formatDay("not-a-day")).toBe("not-a-day");
  });

  it("toggles series but never switches the last one off", () => {
    expect(toggleSeries(["documents", "completed"], "completed")).toEqual(["documents"]);
    expect(toggleSeries(["documents"], "documents")).toEqual(["documents"]);
    expect(toggleSeries(["completed"], "documents")).toEqual(["documents", "completed"]);
  });
});
