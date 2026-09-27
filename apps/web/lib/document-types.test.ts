import { describe, expect, it } from "vitest";
import { documentSourceLabel, documentSourceTitle, documentTypeLabel, isDocumentSource, knownDocumentTypes } from "./document-types";

describe("document type labels", () => {
  it("names the configured types and capitalizes anything else", () => {
    expect(documentTypeLabel("invoice")).toBe("Invoice");
    expect(documentTypeLabel("purchase_order")).toBe("Purchase order");
    expect(documentTypeLabel("delivery_note")).toBe("Delivery note");
    expect(documentTypeLabel("credit_note")).toBe("Credit note");
    expect(documentTypeLabel("")).toBe("Document");
    expect(documentTypeLabel(undefined)).toBe("Document");
    expect(documentTypeLabel(null)).toBe("Document");
  });

  it("lists the types present in canonical order, then unknown types alphabetically", () => {
    const documents = [{ document_type: "delivery_note" }, { document_type: "zeta" }, { document_type: "invoice" }, { document_type: "alpha" }, { document_type: "invoice" }];
    expect(knownDocumentTypes(documents)).toEqual(["invoice", "delivery_note", "alpha", "zeta"]);
    expect(knownDocumentTypes([])).toEqual([]);
  });
});

describe("document sources", () => {
  it("labels the three intake channels and rejects other values", () => {
    expect(documentSourceLabel("upload")).toBe("Upload");
    expect(documentSourceLabel("email")).toBe("Email");
    expect(documentSourceLabel("api")).toBe("API");
    expect(isDocumentSource("sftp")).toBe(false);
    expect(documentSourceLabel("sftp")).toBe("Sftp");
    expect(isDocumentSource(undefined)).toBe(false);
    expect(documentSourceLabel(undefined)).toBe("Upload");
    expect(documentSourceTitle(undefined, null)).toBe("Uploaded in the browser");
  });

  it("explains the channel and the reference the API recorded", () => {
    expect(documentSourceTitle("email", "vendor@example.com · Invoice attached")).toBe("Received by email from vendor@example.com · Invoice attached");
    expect(documentSourceTitle("api", "API key Warehouse")).toBe("Uploaded through the API (API key Warehouse)");
    expect(documentSourceTitle("upload", null)).toBe("Uploaded in the browser");
    expect(documentSourceTitle("upload", "  ")).toBe("Uploaded in the browser");
  });
});
