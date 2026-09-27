import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { COST_NOT_TRACKED, kpiTiles, type MetricsOverview } from "@/lib/metrics";
import { KpiTiles } from "./KpiTile";

const overview: MetricsOverview = {
  range: { days: 7, start: "2026-09-21", end: "2026-09-27", document_type: "purchase_order" },
  documents_processed: 0,
  auto_approve_rate: null,
  field_accuracy: null,
  median_time_to_complete_minutes: null,
  review_queue_depth: 2,
  cost_per_document: null,
  hours_saved: 0,
  baseline_minutes: 12,
  series: [],
};

describe("KpiTiles", () => {
  it("renders seven tiles and reads null metrics as unmeasured instead of zero", () => {
    render(<KpiTiles tiles={kpiTiles(overview)} />);
    const tiles = screen.getAllByRole("group");
    expect(tiles).toHaveLength(7);

    const rate = screen.getByRole("group", { name: "Auto-approve rate" });
    expect(within(rate).getByTestId("kpi-value")).toHaveTextContent("—");
    expect(rate).toHaveAttribute("data-empty", "true");
    expect(within(rate).getByText("No processed documents yet")).toBeInTheDocument();

    const cost = screen.getByRole("group", { name: "Cost per document" });
    expect(within(cost).getByTestId("kpi-value")).toHaveTextContent(COST_NOT_TRACKED);
    expect(within(cost).getByText("Model calls are not metered yet")).toBeInTheDocument();

    const queue = screen.getByRole("group", { name: "Review queue depth" });
    expect(within(queue).getByTestId("kpi-value")).toHaveTextContent("2");
    expect(queue).toHaveAttribute("data-empty", "false");

    const saved = screen.getByRole("group", { name: "Hours saved" });
    expect(within(saved).getByTestId("kpi-value")).toHaveTextContent("0 h");
    expect(within(saved).getByText("Against a 12-minute manual baseline per document")).toBeInTheDocument();
    expect(saved).toHaveAttribute("title", expect.stringContaining("baseline minutes"));
  });

  it("shows dashes on every tile before the overview loads", () => {
    render(<KpiTiles tiles={kpiTiles(undefined)} loading />);
    for (const value of screen.getAllByTestId("kpi-value")) expect(value).toHaveTextContent("—");
    expect(screen.getByRole("group", { name: "Documents processed" }).parentElement).toHaveAttribute("aria-busy", "true");
  });
});
