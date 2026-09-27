// Browser navigations (links, downloads) cannot go through the typed client,
// so the original-file URL is built in exactly one place.
export function documentFileUrl(documentId: string, options: { download?: boolean } = {}): string {
  const base = `/api/v1/documents/${encodeURIComponent(documentId)}/file`;
  return options.download ? `${base}?download=true` : base;
}
