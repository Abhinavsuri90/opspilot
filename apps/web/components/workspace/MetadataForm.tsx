"use client";

import type { FormEvent } from "react";
import type { Category, Collaborator, MetadataDraft, OptionsQuery, Workspace } from "./types";

type MetadataFormProps = {
  data: Workspace;
  metadata: MetadataDraft;
  draft: MetadataDraft | null;
  categories: OptionsQuery<Category>;
  collaborators: OptionsQuery<Collaborator>;
  saving: boolean;
  onChange: (values: Partial<MetadataDraft>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onDiscard: () => void;
};

/** Verified amount, currency, category and reviewer, with a draft that survives polling. */
export function MetadataForm({ data, metadata, draft, categories, collaborators, saving, onChange, onSubmit, onDiscard }: MetadataFormProps) {
  const optionsFailed = categories.isError || collaborators.isError;
  const refreshOptions = () => { void categories.refetch(); void collaborators.refetch(); };
  return <>
    {(!categories.data || !collaborators.data) && <p role={optionsFailed ? "alert" : "status"} className="text-sm text-slate-500">{optionsFailed ? "Could not load editing options." : "Loading editing options…"} <button type="button" onClick={refreshOptions} className="underline">Refresh options</button></p>}
    {categories.data && collaborators.data && <form onSubmit={onSubmit} className="space-y-3 rounded-xl border border-slate-200 p-4"><h4 className="text-sm font-bold">Verified invoice details</h4><p className="text-xs leading-5 text-slate-500">Check the original document, then confirm the amount and currency. Verified amounts power your workspace totals.</p>
      {draft && <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><p>{draft.version !== data.version ? "This invoice changed while you were editing. Your draft is preserved; discard it to load the latest values before saving." : "You have unsaved invoice details. They stay here while you switch views or the invoice refreshes."}</p><button type="button" disabled={saving} className="mt-2 font-semibold underline" onClick={onDiscard}>Discard invoice edits and load latest</button></div>}
      {optionsFailed && <p role="alert" className="text-xs text-rose-700">Could not load all editing options. <button type="button" className="underline" onClick={refreshOptions}>Try again</button></p>}
      <fieldset disabled={!data.capabilities.can_edit || saving} className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-semibold">Category<select className="field mt-1 text-sm" name="category" aria-label="Category" value={metadata.categoryId} onChange={event => onChange({ categoryId: event.target.value })}><option value="">Uncategorized</option>{categories.data?.filter(item => item.active || item.id === metadata.categoryId).map(item => <option key={item.id} value={item.id}>{item.name}{item.active ? "" : " (archived)"}</option>)}</select></label>
        <label className="text-xs font-semibold">Assigned reviewer<select className="field mt-1 text-sm" name="reviewer" aria-label="Assigned reviewer" disabled={!data.capabilities.can_assign} value={metadata.reviewerId} onChange={event => onChange({ reviewerId: event.target.value })}><option value="">Unassigned</option>{metadata.reviewerId && !collaborators.data?.some(item => item.user_id === metadata.reviewerId && ["admin", "reviewer"].includes(item.role)) && <option value={metadata.reviewerId}>Current reviewer (unavailable)</option>}{collaborators.data?.filter(item => item.role === "admin" || item.role === "reviewer").map(item => <option key={item.user_id} value={item.user_id}>{item.email}</option>)}</select></label>
        <label className="text-xs font-semibold">Verified amount<input className="field mt-1 text-sm" name="amount" inputMode="decimal" pattern="[0-9]+([.][0-9]{1,4})?" placeholder="123.45" value={metadata.amount} onChange={event => onChange({ amount: event.target.value })} /></label>
        <label className="text-xs font-semibold">Currency (ISO code)<input className="field mt-1 text-sm uppercase" name="currency" minLength={3} maxLength={3} pattern="[A-Za-z]{3}" placeholder="USD" value={metadata.currency} onChange={event => onChange({ currency: event.target.value })} /></label>
      </fieldset>
      {data.capabilities.can_edit && <button className="secondary text-sm" disabled={saving || !categories.data || !collaborators.data}>Save invoice details</button>}
    </form>}
  </>;
}
