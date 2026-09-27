type ConfidenceBarProps = {
  /** 0..1 score from the confidence engine. */
  confidence: number;
  /** 0..1 threshold the field had to reach to skip review. */
  threshold: number;
  label?: string;
  className?: string;
};

export function percent(value: number): number {
  return Math.round(Math.min(Math.max(value, 0), 1) * 100);
}

/** A confidence meter with the review threshold marked, so a reviewer sees how close a field came. */
export function ConfidenceBar({ confidence, threshold, label = "Confidence", className = "" }: ConfidenceBarProps) {
  const score = percent(confidence);
  const cutoff = percent(threshold);
  const below = confidence < threshold;
  return <div className={`min-w-0 ${className}`}>
    <div className="flex items-baseline justify-between gap-2 text-[11px] font-semibold text-slate-600">
      <span className="tabular-nums" data-testid="confidence-percent">{score}%</span>
      <span className="text-slate-400">threshold {cutoff}%</span>
    </div>
    <div
      role="meter"
      aria-label={`${label} ${score}%, threshold ${cutoff}%`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={score}
      data-below-threshold={below ? "true" : "false"}
      className="relative mt-1 h-2 overflow-hidden rounded-full bg-slate-200"
    >
      <div data-testid="confidence-fill" className={`h-full rounded-full transition-[width] ${below ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${score}%` }} />
      <div data-testid="confidence-threshold" aria-hidden="true" className="absolute inset-y-0 w-0.5 bg-slate-900/70" style={{ left: `calc(${cutoff}% - 1px)` }} />
    </div>
  </div>;
}
