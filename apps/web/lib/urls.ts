// Browser navigations (links, downloads) cannot go through the typed client,
// so the original-file URL is built in exactly one place.
export function documentFileUrl(documentId: string, options: { download?: boolean } = {}): string {
  const base = `/api/v1/documents/${encodeURIComponent(documentId)}/file`;
  return options.download ? `${base}?download=true` : base;
}

/** A month of CSV export from a csv_export connector, served as a download by the API. */
export function exportFileUrl(connectorId: string, month: string): string {
  return `/api/v1/exports/${encodeURIComponent(connectorId)}/${encodeURIComponent(month)}.csv`;
}
