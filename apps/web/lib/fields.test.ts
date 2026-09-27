import { describe, expect, it } from "vitest";
import { dateInputValue, fieldInputKind, summarizeFieldStatuses } from "./fields";

describe("field status summary", () => {
  it("counts each status bucket", () => {
    expect(summarizeFieldStatuses([
      { status: "needs_review" }, { status: "needs_review" }, { status: "auto" }, { status: "corrected" }, { status: "approved" },
    ])).toEqual({ flagged: 2, auto: 1, corrected: 1, accepted: 1 });
    expect(summarizeFieldStatuses([])).toEqual({ flagged: 0, auto: 0, corrected: 0, accepted: 0 });
  });

  it("types the inline editor from the field type", () => {
    expect(fieldInputKind("date")).toBe("date");
    expect(fieldInputKind("money")).toBe("decimal");
    expect(fieldInputKind("integer")).toBe("integer");
    expect(fieldInputKind("identifier")).toBe("text");
    expect(dateInputValue("2026-09-26")).toBe("2026-09-26");
    expect(dateInputValue("26-Sep-2026")).toBe("");
  });
});
