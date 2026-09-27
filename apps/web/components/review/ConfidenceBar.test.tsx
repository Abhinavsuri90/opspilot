import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfidenceBar, percent } from "./ConfidenceBar";

describe("ConfidenceBar", () => {
  it("shows the score as a percentage with the threshold marked", () => {
    render(<ConfidenceBar confidence={0.874} threshold={0.8} label="Vendor confidence" />);
    const meter = screen.getByRole("meter", { name: "Vendor confidence 87%, threshold 80%" });
    expect(meter).toHaveAttribute("aria-valuenow", "87");
    expect(meter).toHaveAttribute("data-below-threshold", "false");
    expect(screen.getByTestId("confidence-percent")).toHaveTextContent("87%");
    expect(screen.getByText("threshold 80%")).toBeInTheDocument();
    expect(screen.getByTestId("confidence-fill")).toHaveStyle({ width: "87%" });
    expect(screen.getByTestId("confidence-fill").className).toContain("bg-emerald-500");
    expect(screen.getByTestId("confidence-threshold")).toHaveStyle({ left: "calc(80% - 1px)" });
  });

  it("uses the warning tone below the threshold", () => {
    render(<ConfidenceBar confidence={0.55} threshold={0.9} />);
    expect(screen.getByRole("meter")).toHaveAttribute("data-below-threshold", "true");
    expect(screen.getByTestId("confidence-fill").className).toContain("bg-amber-500");
    expect(screen.getByTestId("confidence-percent")).toHaveTextContent("55%");
  });

  it("clamps scores outside 0..1", () => {
    expect(percent(1.4)).toBe(100);
    expect(percent(-0.2)).toBe(0);
    expect(percent(0.005)).toBe(1);
  });
});
