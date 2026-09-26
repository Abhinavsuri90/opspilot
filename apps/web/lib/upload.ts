const MAX_PDF_SIZE = 10 * 1024 * 1024;

export function validatePdfSelection(file: Pick<File, "name" | "size">): string | null {
  if (!file.name.toLowerCase().endsWith(".pdf")) return "Choose a PDF invoice.";
  if (file.size === 0 || file.size > MAX_PDF_SIZE) {
    return "Choose a PDF between 1 byte and 10 MB.";
  }
  // Browser MIME labels vary. The API validates the actual PDF bytes.
  return null;
}
