import type { components } from "@/lib/schema";

export type FieldStatus = components["schemas"]["FieldDetail"]["status"];

const chips: Record<FieldStatus, { label: string; className: string }> = {
  auto: { label: "Auto", className: "border-sky-200 bg-sky-50 text-sky-800" },
  needs_review: { label: "Needs review", className: "border-amber-300 bg-amber-50 text-amber-900" },
  corrected: { label: "Corrected", className: "border-violet-200 bg-violet-50 text-violet-800" },
  approved: { label: "Approved", className: "border-emerald-200 bg-emerald-50 text-emerald-800" },
};

export function fieldStatusLabel(status: FieldStatus): string {
  return chips[status].label;
}

/** How a single extracted field stands: accepted automatically, flagged, edited or accepted by a person. */
export function FieldStatusChip({ status, className = "" }: { status: FieldStatus; className?: string }) {
  const chip = chips[status];
  return <span data-status={status} className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-bold ${chip.className} ${className}`}>{chip.label}</span>;
}
