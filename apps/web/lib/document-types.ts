// Labels for the document types and intake channels the workflow configuration
// can produce. The API stores snake_case identifiers; people read words.

export const DOCUMENT_TYPES = ["invoice", "purchase_order", "delivery_note"] as const;
export type KnownDocumentType = (typeof DOCUMENT_TYPES)[number];

const typeLabels: Record<string, string> = {
  invoice: "Invoice",
  purchase_order: "Purchase order",
  delivery_note: "Delivery note",
};

/** "Purchase order" for purchase_order; unknown types read as their words with a capital, and a missing type as "Document". */
export function documentTypeLabel(type: string | null | undefined): string {
  if (!type) return "Document";
  const known = typeLabels[type];
  if (known) return known;
  const words = type.replaceAll("_", " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Document";
}

/**
 * Distinct types present in a list, known types first in their canonical order,
 * then anything else alphabetically, so filter menus are stable between refreshes.
 */
export function knownDocumentTypes(documents: readonly { document_type: string }[]): string[] {
  const present = new Set(documents.map(item => item.document_type).filter(Boolean));
  const canonical = DOCUMENT_TYPES.filter(type => present.has(type));
  const extra = [...present].filter(type => !(DOCUMENT_TYPES as readonly string[]).includes(type)).sort();
  return [...canonical, ...extra];
}

export const DOCUMENT_SOURCES = ["upload", "email", "api"] as const;
export type DocumentSource = (typeof DOCUMENT_SOURCES)[number];

const sourceLabels: Record<DocumentSource, string> = { upload: "Upload", email: "Email", api: "API" };

export function isDocumentSource(value: string | null | undefined): value is DocumentSource {
  return typeof value === "string" && (DOCUMENT_SOURCES as readonly string[]).includes(value);
}

/** "Upload" when the channel is unknown or missing: every document was at least uploaded. */
export function documentSourceLabel(source: string | null | undefined): string {
  return isDocumentSource(source) ? sourceLabels[source] : source ? documentTypeLabel(source) : sourceLabels.upload;
}

/** The tooltip behind a source badge: which channel, plus the sender or key the API recorded. */
export function documentSourceTitle(source: string | null | undefined, sourceRef: string | null | undefined): string {
  const ref = sourceRef?.trim();
  switch (source) {
    case "email": return ref ? `Received by email from ${ref}` : "Received by email";
    case "api": return ref ? `Uploaded through the API (${ref})` : "Uploaded through the API";
    case "upload":
    case undefined:
    case null:
    case "": return ref ? `Uploaded in the browser (${ref})` : "Uploaded in the browser";
    default: return ref ? `${documentSourceLabel(source)} (${ref})` : documentSourceLabel(source);
  }
}
