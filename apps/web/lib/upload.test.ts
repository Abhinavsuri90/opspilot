import { describe, expect, it } from "vitest";
import { validatePdfSelection } from "./upload";

describe("PDF selection", () => {
  it("accepts a PDF even when the browser reports an unknown MIME type", () => {
    expect(validatePdfSelection({ name: "invoice.PDF", size: 1024 })).toBeNull();
  });

  it("rejects wrong extensions and empty or oversized files", () => {
    expect(validatePdfSelection({ name: "invoice.txt", size: 1024 })).toBe("Choose a PDF document.");
    expect(validatePdfSelection({ name: "invoice.pdf", size: 0 })).toContain("between 1 byte");
    expect(validatePdfSelection({ name: "invoice.pdf", size: 10 * 1024 * 1024 + 1 })).toContain("10 MB");
  });
});
