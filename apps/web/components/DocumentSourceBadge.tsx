import { documentSourceLabel, documentSourceTitle, isDocumentSource, type DocumentSource } from "@/lib/document-types";

const tones: Record<DocumentSource, string> = {
  upload: "border-slate-200 bg-slate-50 text-slate-600",
  email: "border-violet-200 bg-violet-50 text-violet-800",
  api: "border-cyan-200 bg-cyan-50 text-cyan-800",
};

function SourceIcon({ source }: { source: DocumentSource }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" {...common}>
    {source === "upload" && <><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M4 20h16" /></>}
    {source === "email" && <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>}
    {source === "api" && <><path d="m8 8-4 4 4 4" /><path d="m16 8 4 4-4 4" /><path d="m14 4-4 16" /></>}
  </svg>;
}

/** Where a document came from: a browser upload, an email attachment or an API key; the reference shows on hover. */
export function DocumentSourceBadge({ source, sourceRef, className = "" }: { source: string | null | undefined; sourceRef?: string | null; className?: string }) {
  const known: DocumentSource = isDocumentSource(source) ? source : "upload";
  return <span data-source={known} title={documentSourceTitle(source, sourceRef)} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${tones[known]} ${className}`}>
    <SourceIcon source={known} />
    <span>{documentSourceLabel(source)}</span>
    <span className="sr-only">. {documentSourceTitle(source, sourceRef)}</span>
  </span>;
}
