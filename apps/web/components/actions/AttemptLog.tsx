"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { ActionDetail } from "@/lib/actions";
import { formatDateTime } from "@/lib/format";

type AttemptLogProps = {
  actionId: string;
  defaultOpen?: boolean;
  /** Refetch when the list shows a newer version of the action. */
  version: number;
};

/** Every delivery attempt with its response summary or error, fetched only when opened. */
export function AttemptLog({ actionId, defaultOpen = false, version }: AttemptLogProps) {
  const [open, setOpen] = useState(defaultOpen);
  const detail = useQuery({
    queryKey: ["action", actionId, version],
    enabled: open,
    queryFn: async (): Promise<ActionDetail> => {
      const result = await api.GET("/v1/actions/{action_id}", { params: { path: { action_id: actionId } } });
      if (result.error || !result.data) throw new Error("Could not load the attempt history.");
      return result.data;
    },
  });
  const attempts = detail.data?.attempt_log ?? [];
  const result = detail.data?.result;
  return <details className="mt-3" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer text-xs font-semibold text-slate-600">Attempt history{detail.data ? ` (${attempts.length})` : ""}</summary>
    <div className="mt-2 space-y-2">
      {detail.isLoading && <p role="status" className="text-xs text-slate-500">Loading attempts…</p>}
      {detail.isError && <p role="alert" className="text-xs text-rose-700">{detail.error.message} <button type="button" className="underline" onClick={() => detail.refetch()}>Try again</button></p>}
      {detail.data && attempts.length === 0 && <p className="text-xs text-slate-500">The connector has not been called yet.</p>}
      {attempts.length > 0 && <ol className="divide-y divide-slate-100 rounded-xl border border-slate-200 text-xs" aria-label="Delivery attempts">
        {attempts.map(attempt => <li key={attempt.attempt} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2" data-ok={attempt.ok}>
          <span className={`font-bold ${attempt.ok ? "text-emerald-700" : "text-rose-700"}`}>#{attempt.attempt} {attempt.ok ? "ok" : "failed"}</span>
          <time dateTime={attempt.finished_at} className="text-slate-500">{formatDateTime(attempt.finished_at)}</time>
          <span className="min-w-0 flex-1 break-words text-slate-700">{attempt.response_summary ?? attempt.error ?? "—"}</span>
        </li>)}
      </ol>}
      {result && Object.keys(result).length > 0 && <details><summary className="cursor-pointer text-xs font-semibold text-slate-600">Result</summary><pre className="mt-1 overflow-x-auto rounded-xl bg-slate-50 p-3 font-mono text-[11px] text-slate-800">{JSON.stringify(result, null, 2)}</pre></details>}
    </div>
  </details>;
}
