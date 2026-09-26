export function isDocumentInProgress(status: string): boolean {
  return status === "queued" || status === "extracting" || status === "validating";
}

export function documentStatusLabel(status: string): string {
  return status.replaceAll("_", " ");
}
