import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("gives the Phase 2 statuses the tone of their workflow family", () => {
    render(<><StatusBadge status="validating" /><StatusBadge status="auto_approved" /><StatusBadge status="needs_review" /></>);
    expect(screen.getByText("Validating")).toHaveAttribute("data-tone", "progress");
    expect(screen.getByText("Validating").className).toContain("bg-blue-50");
    expect(screen.getByText("Auto-approved")).toHaveAttribute("data-tone", "completed");
    expect(screen.getByText("Auto-approved").className).toContain("bg-emerald-50");
    expect(screen.getByText("Needs review").className).toContain("bg-amber-50");
  });
});
