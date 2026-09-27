// Pure helpers behind the dashboard KPIs: how a rate, a duration or a missing
// value reads on a tile, and how the daily series becomes chart rows.

import type { components } from "@/lib/schema";

export type MetricsOverview = components["schemas"]["MetricsOverview"];
export type SeriesPoint = components["schemas"]["SeriesPoint"];

export const METRIC_RANGES = [7, 30, 90] as const;
export type MetricRange = (typeof METRIC_RANGES)[number];
export const DEFAULT_METRIC_RANGE: MetricRange = 30;

export function isMetricRange(value: number): value is MetricRange {
  return (METRIC_RANGES as readonly number[]).includes(value);
}

/** The KPIs are aggregates; a minute of staleness is fine and keeps the API quiet. */
export const METRICS_POLL_MS = 60_000;

export const EMPTY_VALUE = "—";

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return Math.round(value).toLocaleString("en-US");
}

/** 0.8251 reads "82.5%", 1 reads "100%"; nothing measured reads a dash. */
export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  const percent = Math.min(100, Math.max(0, value * 100));
  const rounded = Math.round(percent * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}%`;
}

/** Minutes as people say them: "<1 min", "12 min", "1 h 5 min", "2 h". */
export function formatMinutes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  const minutes = Math.max(0, value);
  if (minutes === 0) return "0 min";
  if (minutes < 1) return "<1 min";
  const whole = Math.round(minutes);
  if (whole < 60) return `${whole} min`;
  const hours = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest > 0 ? `${hours} h ${rest} min` : `${hours} h`;
}

/** Hours saved: whole hours once large, one decimal while small, never negative. */
export function formatHours(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  const hours = Math.max(0, value);
  if (hours >= 100) return `${Math.round(hours).toLocaleString("en-US")} h`;
  const rounded = Math.round(hours * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)} h`;
}

export const COST_NOT_TRACKED = "Not tracked yet";

/** Cost per document is null until model calls are metered; the tile says so instead of showing a zero. */
export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return COST_NOT_TRACKED;
  const amount = Math.max(0, value);
  return `${amount < 1 ? amount.toFixed(3) : amount.toFixed(2)}¢`;
}

export type KpiTone = "primary" | "review" | "completed" | "neutral";

export type KpiTileModel = {
  id: string;
  label: string;
  value: string;
  detail: string;
  /** The plain-language definition shown in the disclosure and as the tile's tooltip. */
  definition: string;
  tone: KpiTone;
  /** True when the metric has no measurement yet, so the value renders quietly. */
  empty: boolean;
};

const definitions = {
  documents_processed: "Documents created in the range that reached a decision path: extracted and either auto-approved, queued for review or already decided. Queued, extracting, validating and failed documents are not counted.",
  auto_approve_rate: "Processed documents that never needed a review task, divided by all processed documents.",
  field_accuracy: "1 minus (fields a reviewer edited ÷ fields assessed) across the latest extraction run of each processed document. Accepting a field as-is counts as accurate.",
  median_time_to_complete: "Median of review task completion minus its opening, in minutes. Auto-approved documents count as zero minutes.",
  review_queue_depth: "Documents waiting for a human decision right now, regardless of the range.",
  cost_per_document: "Priced model-call spend in US cents divided by processed documents. Unpriced calls are excluded. This is an estimate from the local pricing table, not a provider bill.",
  escalation_rate: "Latest extraction runs that called a second model divided by latest runs for processed documents. Empty until there are extraction runs.",
  hours_saved: "Processed documents × the baseline minutes a manual entry takes, minus the minutes reviewers actually spent, floored at zero and expressed in hours.",
} as const;

export function kpiDefinitions(): { id: string; label: string; definition: string }[] {
  return [
    { id: "documents_processed", label: "Documents processed", definition: definitions.documents_processed },
    { id: "auto_approve_rate", label: "Auto-approve rate", definition: definitions.auto_approve_rate },
    { id: "field_accuracy", label: "Field accuracy", definition: definitions.field_accuracy },
    { id: "median_time_to_complete", label: "Median time to complete", definition: definitions.median_time_to_complete },
    { id: "review_queue_depth", label: "Review queue depth", definition: definitions.review_queue_depth },
    { id: "cost_per_document", label: "Cost per document", definition: definitions.cost_per_document },
    { id: "escalation_rate", label: "Model escalation", definition: definitions.escalation_rate },
    { id: "hours_saved", label: "Hours saved", definition: definitions.hours_saved },
  ];
}

const isMissing = (value: number | null | undefined) => value === null || value === undefined || !Number.isFinite(value);

/** The eight tiles, in reading order. Without data every value is a dash so the layout never jumps. */
export function kpiTiles(overview: MetricsOverview | undefined): KpiTileModel[] {
  const days = overview?.range.days;
  const rangeLabel = days ? `last ${days} days` : "selected range";
  const baseline = overview?.baseline_minutes;
  return [
    { id: "documents_processed", label: "Documents processed", value: overview ? formatCount(overview.documents_processed) : EMPTY_VALUE, detail: `Reached a decision path in the ${rangeLabel}`, definition: definitions.documents_processed, tone: "primary", empty: !overview },
    { id: "auto_approve_rate", label: "Auto-approve rate", value: overview ? formatRate(overview.auto_approve_rate) : EMPTY_VALUE, detail: !overview || isMissing(overview.auto_approve_rate) ? "No processed documents yet" : "Approved by policy without a reviewer", definition: definitions.auto_approve_rate, tone: "completed", empty: !overview || isMissing(overview.auto_approve_rate) },
    { id: "field_accuracy", label: "Field accuracy", value: overview ? formatRate(overview.field_accuracy) : EMPTY_VALUE, detail: !overview || isMissing(overview.field_accuracy) ? "No fields assessed yet" : "Fields that needed no correction", definition: definitions.field_accuracy, tone: "primary", empty: !overview || isMissing(overview.field_accuracy) },
    { id: "median_time_to_complete", label: "Median time to complete", value: overview ? formatMinutes(overview.median_time_to_complete_minutes) : EMPTY_VALUE, detail: !overview || isMissing(overview.median_time_to_complete_minutes) ? "No completed reviews yet" : "From review opened to decision", definition: definitions.median_time_to_complete, tone: "neutral", empty: !overview || isMissing(overview.median_time_to_complete_minutes) },
    { id: "review_queue_depth", label: "Review queue depth", value: overview ? formatCount(overview.review_queue_depth) : EMPTY_VALUE, detail: "Waiting for a human decision now", definition: definitions.review_queue_depth, tone: "review", empty: !overview },
    { id: "cost_per_document", label: "Cost per document", value: overview ? formatCost(overview.cost_per_document) : EMPTY_VALUE, detail: !overview || isMissing(overview.cost_per_document) ? "No priced model calls in this range" : "Estimated model spend per document · US cents", definition: definitions.cost_per_document, tone: "neutral", empty: !overview || isMissing(overview.cost_per_document) },
    { id: "escalation_rate", label: "Model escalation", value: overview ? formatRate(overview.escalation_rate) : EMPTY_VALUE, detail: !overview || isMissing(overview.escalation_rate) ? "No extraction runs in this range" : `${formatCount(overview.escalated_documents)} documents used a second model`, definition: definitions.escalation_rate, tone: "review", empty: !overview || isMissing(overview.escalation_rate) },
    { id: "hours_saved", label: "Hours saved", value: overview ? formatHours(overview.hours_saved) : EMPTY_VALUE, detail: baseline === undefined ? "Against a manual-entry baseline" : `Against a ${baseline}-minute manual baseline per document`, definition: definitions.hours_saved, tone: "completed", empty: !overview },
  ];
}

// Series colors follow the app palette (cyan primary, amber for review, emerald
// for completed) in an order whose adjacent pairs stay apart under color blindness.
export const CHART_SERIES = [
  { key: "documents", label: "Documents", color: "#0891b2", description: "Documents that reached a decision path that day" },
  { key: "needs_review", label: "Needs review", color: "#d97706", description: "Documents that opened a review task that day" },
  { key: "auto_approved", label: "Auto-approved", color: "#2563eb", description: "Documents approved by policy that day" },
  { key: "completed", label: "Completed", color: "#059669", description: "Reviews completed that day" },
] as const;

export type ChartSeriesKey = (typeof CHART_SERIES)[number]["key"];

export function isChartSeriesKey(value: string): value is ChartSeriesKey {
  return CHART_SERIES.some(series => series.key === value);
}

export type SeriesRow = { day: string; label: string } & Record<ChartSeriesKey, number>;

const dayFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** "Sep 27" for an ISO day; the raw value when it cannot be parsed. */
export function formatDay(day: string): string {
  const parsed = Date.parse(`${day}T00:00:00Z`);
  return Number.isNaN(parsed) ? day : dayFormat.format(new Date(parsed));
}

/** Chart rows in day order with the four plotted counts, ready for Recharts and the data table. */
export function seriesRows(series: readonly SeriesPoint[]): SeriesRow[] {
  return [...series]
    .sort((a, b) => a.day.localeCompare(b.day))
    .map(point => ({
      day: point.day,
      label: formatDay(point.day),
      documents: point.documents,
      needs_review: point.needs_review,
      auto_approved: point.auto_approved,
      completed: point.completed,
    }));
}

/** Which series to plot after a toggle: at least one always stays on. */
export function toggleSeries(active: readonly ChartSeriesKey[], key: ChartSeriesKey): ChartSeriesKey[] {
  if (active.includes(key)) return active.length === 1 ? [...active] : active.filter(item => item !== key);
  return CHART_SERIES.map(series => series.key).filter(item => item === key || active.includes(item));
}
