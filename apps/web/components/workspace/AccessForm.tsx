"use client";

import type { FormEvent } from "react";
import type { Collaborator, OptionsQuery, SharingDraft, Workspace } from "./types";

type AccessFormProps = {
  data: Workspace;
  sharing: SharingDraft;
  draft: SharingDraft | null;
  collaborators: OptionsQuery<Collaborator>;
  saving: boolean;
  onChange: (values: Partial<SharingDraft>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onDiscard: () => void;
};

/** Workspace-wide or restricted visibility plus explicit grants, with a draft that survives polling. */
export function AccessForm({ data, sharing, draft, collaborators, saving, onChange, onSubmit, onDiscard }: AccessFormProps) {
  if (!collaborators.data) {
    return <p role={collaborators.isError ? "alert" : "status"} className="text-sm text-slate-500">Could not load access options yet. <button type="button" onClick={() => collaborators.refetch()} className="underline">Refresh</button></p>;
  }
  return <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-slate-200 p-4"><div><h4 className="text-sm font-bold">Document access</h4><p className="mt-1 text-xs leading-5 text-slate-500">Links require sign-in. Restricted invoices are visible to admins, the uploader, the assigned reviewer and selected teammates.</p></div>{draft && <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><p>{draft.version !== data.version ? "This invoice changed while you were editing access. Your choices are preserved; discard them to load the latest access settings." : "You have unsaved access changes."}</p><button type="button" disabled={saving} className="mt-2 font-semibold underline" onClick={onDiscard}>Discard access edits and load latest</button></div>}<fieldset disabled={!data.capabilities.can_share || saving} className="space-y-3"><label className="text-xs font-semibold">Visibility<select className="field mt-1 text-sm" name="visibility" aria-label="Visibility" value={sharing.visibility} onChange={event => onChange({ visibility: event.target.value === "restricted" ? "restricted" : "workspace" })}><option value="workspace">Everyone approved in this organization</option><option value="restricted">Only selected people</option></select></label><p className="text-xs font-semibold">Selected teammates</p>{collaborators.isError && <p role="alert" className="text-xs text-rose-700">Could not load teammates. Refresh before editing access.</p>}<div className="max-h-52 space-y-2 overflow-auto">{collaborators.data.map(item => <label key={item.user_id} className="flex items-center gap-2 text-xs"><input type="checkbox" name="grants" value={item.user_id} checked={sharing.userIds.includes(item.user_id)} onChange={event => onChange({ userIds: event.target.checked ? [...sharing.userIds, item.user_id] : sharing.userIds.filter(id => id !== item.user_id) })} /><span className="break-all">{item.email} <span className="text-slate-400">· {item.role}</span></span></label>)}</div>{data.capabilities.can_share && <button className="primary text-sm" disabled={saving}>Save access</button>}</fieldset></form>;
}
