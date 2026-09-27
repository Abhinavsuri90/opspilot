import { documentStatusLabel, documentStatusTone, type DocumentStatusTone } from "@/lib/document-status";

// One tone per workflow family, so validating and auto-approved documents look
// like the in-progress and completed states they belong to.
export const badgeTones: Record<DocumentStatusTone, string> = {
  progress: "border-blue-200 bg-blue-50 text-blue-700",
  review: "border-amber-200 bg-amber-50 text-amber-800",
  completed: "border-emerald-200 bg-emerald-50 text-emerald-800",
  rejected: "border-slate-200 bg-slate-100 text-slate-600",
  failed: "border-rose-200 bg-rose-50 text-rose-700",
  neutral: "border-slate-200 bg-slate-50 text-slate-600",
};

export function StatusBadge({ status, className = "" }: { status: string; className?: string }) {
  const tone = documentStatusTone(status);
  return <span data-tone={tone} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold capitalize ${badgeTones[tone]} ${className}`}>
    <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />{documentStatusLabel(status)}
  </span>;
}
