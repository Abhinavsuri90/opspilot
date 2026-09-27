// Pure helpers for the review queue: the filter model, how it becomes API
// query parameters, and how an SLA deadline reads to a person.

export const QUEUE_PAGE_SIZE = 25;

export type QueueAge = "any" | "1" | "4" | "24";
export type QueueAssigned = "all" | "me" | "unassigned";

export type QueueFilters = {
  documentType: string;
  vendor: string;
  age: QueueAge;
  assigned: QueueAssigned;
};

export const DEFAULT_QUEUE_FILTERS: QueueFilters = { documentType: "", vendor: "", age: "any", assigned: "all" };

export const AGE_OPTIONS: { value: QueueAge; label: string }[] = [
  { value: "any", label: "Any time" },
  { value: "1", label: "Last hour" },
  { value: "4", label: "Last 4 hours" },
  { value: "24", label: "Last 24 hours" },
];

export type QueueQuery = {
  document_type?: string;
  vendor?: string;
  max_age_hours?: number;
  assigned?: QueueAssigned;
  offset: number;
  limit: number;
};

/** Only filters with a value reach the API; the defaults stay off the wire. */
export function buildQueueQuery(filters: QueueFilters, offset = 0): QueueQuery {
  const query: QueueQuery = { offset: Math.max(0, offset), limit: QUEUE_PAGE_SIZE };
  const documentType = filters.documentType.trim();
  const vendor = filters.vendor.trim();
  if (documentType) query.document_type = documentType;
  if (vendor) query.vendor = vendor.slice(0, 200);
  if (filters.age !== "any") query.max_age_hours = Number(filters.age);
  if (filters.assigned !== "all") query.assigned = filters.assigned;
  return query;
}

export function queueFiltersActive(filters: QueueFilters, overdueOnly = false): boolean {
  return overdueOnly || filters.documentType.trim() !== "" || filters.vendor.trim() !== "" || filters.age !== "any" || filters.assigned !== "all";
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "3h 58m", "42m", "2d 3h" or "<1m" for a duration in milliseconds. */
export function formatSpan(milliseconds: number): string {
  const total = Math.abs(milliseconds);
  if (total < MINUTE) return "<1m";
  if (total >= DAY) {
    const days = Math.floor(total / DAY);
    const hours = Math.floor((total % DAY) / HOUR);
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }
  const hours = Math.floor(total / HOUR);
  const minutes = Math.floor((total % HOUR) / MINUTE);
  if (hours === 0) return `${minutes}m`;
  return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
}

export type SlaState = { label: string; overdue: boolean; known: boolean };

/** How an SLA deadline reads right now: "Due in 3h 58m" or "Overdue by 12m". */
export function formatSla(dueAt: string | null | undefined, now: number = Date.now()): SlaState {
  if (!dueAt) return { label: "No SLA", overdue: false, known: false };
  const due = Date.parse(dueAt);
  if (Number.isNaN(due)) return { label: "No SLA", overdue: false, known: false };
  const remaining = due - now;
  if (remaining < 0) return { label: `Overdue by ${formatSpan(remaining)}`, overdue: true, known: true };
  return { label: `Due in ${formatSpan(remaining)}`, overdue: false, known: true };
}

/** Amount plus currency as the queue shows it: "1,234.50 USD", or a dash when unknown. */
export function formatQueueTotal(total: string | null, currency: string | null): string {
  if (!total) return "—";
  const digits = total.replace(/[^0-9.-]/g, "");
  const numeric = /\d/.test(digits) ? Number(digits) : Number.NaN;
  const amount = Number.isFinite(numeric) ? numeric.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : total.trim();
  return currency ? `${amount} ${currency}` : amount;
}
