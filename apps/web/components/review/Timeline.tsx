import { formatDateTime } from "@/lib/format";
import type { components } from "@/lib/schema";

export type TimelineEntry = components["schemas"]["TimelineEntry"];

const kinds: Record<TimelineEntry["kind"], { label: string; glyph: string; className: string }> = {
  audit: { label: "Audit", glyph: "◦", className: "bg-slate-100 text-slate-600" },
  extraction: { label: "Extraction", glyph: "▤", className: "bg-sky-100 text-sky-800" },
  correction: { label: "Correction", glyph: "✎", className: "bg-violet-100 text-violet-800" },
  review: { label: "Review", glyph: "✓", className: "bg-emerald-100 text-emerald-800" },
  comment: { label: "Comment", glyph: "❝", className: "bg-amber-100 text-amber-800" },
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

type TimelineProps = {
  entries: TimelineEntry[] | undefined;
  isLoading: boolean;
  isError: boolean;
  refetch: () => unknown;
};

/** Everything that happened to a document, oldest first, with the raw detail one click away. */
export function Timeline({ entries, isLoading, isError, refetch }: TimelineProps) {
  return <section aria-label="Document timeline">
    {isLoading && <p role="status" className="text-sm text-slate-500">Loading timeline…</p>}
    {isError && <p role="alert" className="text-sm text-rose-700">Could not load the timeline. <button type="button" className="underline" onClick={() => refetch()}>Try again</button></p>}
    {entries && entries.length === 0 && <p className="text-sm text-slate-500">Nothing has happened to this document yet.</p>}
    {entries && entries.length > 0 && <ol className="relative space-y-4 border-l-2 border-slate-200 pl-6">
      {entries.map((entry, index) => {
        const kind = kinds[entry.kind];
        const detail = Object.entries(entry.detail).filter(([key]) => key !== "document_id");
        return <li key={`${entry.at}-${entry.event_type}-${index}`} className="relative text-sm" data-kind={entry.kind}>
          <span aria-hidden="true" className={`absolute -left-[31px] grid h-6 w-6 place-items-center rounded-full text-xs font-bold ring-4 ring-white ${kind.className}`}>{kind.glyph}</span>
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${kind.className}`}>{kind.label}</span>
            <time dateTime={entry.at} className="text-xs text-slate-500">{formatDateTime(entry.at)}</time>
            {entry.actor_email && <span className="break-all text-xs text-slate-500">· {entry.actor_email}</span>}
          </div>
          <p className="mt-1 font-semibold text-slate-900">{entry.summary}</p>
          {detail.length > 0 && <details className="mt-1">
            <summary className="cursor-pointer text-xs font-semibold text-slate-600">Details</summary>
            <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
              {detail.map(([key, value]) => <div key={key} className="contents">
                <dt className="font-semibold text-slate-500">{key.replaceAll("_", " ")}</dt>
                <dd className="min-w-0"><pre className="whitespace-pre-wrap break-words font-sans text-slate-800">{formatValue(value)}</pre></dd>
              </div>)}
            </dl>
          </details>}
        </li>;
      })}
    </ol>}
  </section>;
}
