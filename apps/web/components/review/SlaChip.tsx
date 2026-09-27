import { formatSla } from "@/lib/review-queue";

type SlaChipProps = {
  dueAt: string | null | undefined;
  completedAt?: string | null;
  outcome?: string | null;
  now: number;
  className?: string;
};

/** The SLA clock for a review task: counting down, overdue in red, or finished. */
export function SlaChip({ dueAt, completedAt, outcome, now, className = "" }: SlaChipProps) {
  if (completedAt) {
    return <span className={`inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold capitalize text-slate-600 ${className}`}>Review {outcome ?? "completed"}</span>;
  }
  const sla = formatSla(dueAt, now);
  if (!sla.known) return <span className={`inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-500 ${className}`}>No SLA</span>;
  return <span data-overdue={sla.overdue ? "true" : "false"} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold tabular-nums ${sla.overdue ? "border-rose-200 bg-rose-50 text-rose-700" : "border-slate-200 bg-white text-slate-700"} ${className}`}>
    <span aria-hidden="true">{sla.overdue ? "!" : "◷"}</span>{sla.label}
  </span>;
}
