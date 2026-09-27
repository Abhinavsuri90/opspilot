import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DiffPreview } from "./DiffPreview";

describe("DiffPreview", () => {
  it("renders the values an action sends as a field/value table with the connector's request lines", () => {
    render(<DiffPreview preview={{ kind: "post_webhook", title: "POST https://hooks.example.com/opspilot", before: null, after: { vendor: "Northwind Traders", total: "1234.50" }, lines: ["POST https://hooks.example.com/opspilot", "Signed with HMAC-SHA256", "vendor: Northwind Traders"] }} />);
    const table = screen.getByRole("table", { name: "Values the action sends" });
    expect(within(table).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["Field", "Value"]);
    expect(within(table).getByRole("row", { name: /vendor/ })).toHaveTextContent("Northwind Traders");
    expect(within(table).getByRole("row", { name: /total/ })).toHaveTextContent("1234.50");
    expect(screen.getByText("POST https://hooks.example.com/opspilot", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText(/Signed with HMAC-SHA256/)).toBeInTheDocument();
  });

  it("shows before and after columns and marks only the rows that change", () => {
    render(<DiffPreview preview={{ kind: "create_record", title: "INSERT INTO public.invoices", before: { vendor: "Old Co", total: "1.00" }, after: { vendor: "Old Co", total: "2.00" }, lines: [] }} />);
    const table = screen.getByRole("table", { name: "Values before and after the action" });
    expect(within(table).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["Field", "Before", "After"]);
    const total = within(table).getByRole("row", { name: /total/ });
    expect(total).toHaveAttribute("data-changed", "true");
    expect(within(total).getByText("1.00")).toBeInTheDocument();
    expect(within(total).getByText("2.00")).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /vendor/ })).not.toHaveAttribute("data-changed");
  });

  it("folds long request lines behind a disclosure in compact mode and explains an empty payload", () => {
    render(<DiffPreview compact preview={{ kind: "export_csv", title: "", before: null, after: {}, lines: ["append row to export-2026-09.csv"] }} />);
    expect(screen.getByText("Request lines")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    render(<DiffPreview preview={{ kind: "export_csv", title: "", before: null, after: {}, lines: [] }} />);
    expect(screen.getByText("This action sends no values.")).toBeInTheDocument();
  });
});
