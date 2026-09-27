"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ConfidenceBar } from "@/components/review/ConfidenceBar";
import { FieldStatusChip } from "@/components/review/FieldStatusChip";
import { dateInputValue, fieldInputKind, type FieldDetail } from "@/lib/fields";

export type FieldRowProps = {
  field: FieldDetail;
  index: number;
  focused: boolean;
  editing: boolean;
  saving: boolean;
  error: string | null;
  /** The document awaits review and this person may accept or edit fields. */
  canAct: boolean;
  highlighted: boolean;
  itemRef: (element: HTMLLIElement | null) => void;
  onFocus: () => void;
  onAccept: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: (value: string) => void;
  onFindEvidence: () => void;
};

function signalLabel(name: string): string {
  return name.replaceAll("_", " ");
}

function InlineEditor({ field, saving, error, onCancel, onSave }: { field: FieldDetail; saving: boolean; error: string | null; onCancel: () => void; onSave: (value: string) => void }) {
  const kind = fieldInputKind(field.field_type);
  const [draft, setDraft] = useState(() => kind === "date" ? dateInputValue(field.current_value) : field.current_value);
  const [localError, setLocalError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const inputId = `field-editor-${field.id}`;
  const shownError = localError ?? error;
  useEffect(() => { input.current?.focus(); input.current?.select(); }, []);
  function submit() {
    if (saving) return;
    if (!draft.trim()) { setLocalError("Enter a value before saving."); return; }
    setLocalError(null);
    onSave(draft);
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") { event.preventDefault(); submit(); }
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onCancel(); }
  }
  return <form className="mt-3 space-y-2" onSubmit={event => { event.preventDefault(); submit(); }} aria-label={`Edit ${field.label}`}>
    <label htmlFor={inputId} className="block text-xs font-semibold text-slate-700">New value for {field.label}</label>
    <input
      ref={input}
      id={inputId}
      className="field text-sm"
      type={kind === "date" ? "date" : "text"}
      inputMode={kind === "decimal" ? "decimal" : kind === "integer" ? "numeric" : undefined}
      value={draft}
      readOnly={saving}
      aria-busy={saving || undefined}
      onChange={event => { setDraft(event.target.value); setLocalError(null); }}
      onKeyDown={onKeyDown}
      aria-invalid={shownError ? true : undefined}
      aria-describedby={shownError ? `${inputId}-error` : `${inputId}-hint`}
    />
    {shownError ? <p id={`${inputId}-error`} role="alert" className="text-xs font-semibold text-rose-700">{shownError}</p> : <p id={`${inputId}-hint`} className="text-xs text-slate-500">Enter saves · Escape cancels</p>}
    <div className="flex gap-2">
      <button type="submit" className="primary min-h-9 px-3 text-xs" disabled={saving}>{saving ? "Saving…" : "Save value"}</button>
      <button type="button" className="secondary min-h-9 px-3 text-xs" disabled={saving} onClick={onCancel}>Cancel</button>
    </div>
  </form>;
}

/** One extracted field: value, evidence, confidence against its threshold, and the reviewer's actions. */
export function FieldRow({ field, index, focused, editing, saving, error, canAct, highlighted, itemRef, onFocus, onAccept, onStartEdit, onCancelEdit, onSaveEdit, onFindEvidence }: FieldRowProps) {
  const flagged = field.status === "needs_review";
  const acceptable = field.status === "auto" || field.status === "needs_review";
  const signals = Object.entries(field.signals);
  return <li
    ref={itemRef}
    tabIndex={focused ? 0 : -1}
    data-field-index={index}
    data-field-name={field.name}
    data-focused={focused ? "true" : "false"}
    aria-label={`${field.label} field`}
    onFocus={onFocus}
    className={`rounded-2xl border bg-white p-4 outline-none transition-shadow focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${flagged ? "border-amber-300" : "border-slate-200"} ${highlighted ? "shadow-[0_0_0_2px_rgba(245,158,11,.5)]" : ""}`}
  >
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{field.label}{field.required && <span className="text-rose-600" title="Required"> *</span>}</p>
        <p className="mt-1 break-words text-base font-bold text-slate-900" data-testid="field-value">{field.current_value || <span className="text-slate-400">empty</span>}</p>
        {field.status === "corrected" && <p className="mt-1 text-xs text-slate-500">Extracted <s className="text-slate-400">{field.value || "empty"}</s>{field.corrected_by_email && <> · edited by <span className="break-all">{field.corrected_by_email}</span></>}</p>}
        {field.status === "approved" && field.corrected_by_email && <p className="mt-1 text-xs text-slate-500">Accepted by <span className="break-all">{field.corrected_by_email}</span></p>}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <FieldStatusChip status={field.status} />
        <button type="button" className="secondary min-h-8 px-2.5 text-[11px]" aria-pressed={highlighted} onClick={onFindEvidence} aria-label={`Find evidence for ${field.label} on page ${field.page_number}`}>Find evidence · p.{field.page_number}</button>
      </div>
    </div>
    <ConfidenceBar confidence={field.confidence} threshold={field.threshold} label={`${field.label} confidence`} className="mt-3" />
    <details className="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-xs">
      <summary className={`cursor-pointer font-semibold ${flagged ? "text-amber-900" : "text-slate-600"}`}>{flagged ? "Why flagged" : "Confidence signals"}</summary>
      {field.reasons.length > 0 ? <ul className="mt-2 list-disc space-y-1 pl-4 text-slate-700">{field.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul> : <p className="mt-2 text-slate-500">No problems were reported for this field.</p>}
      {signals.length > 0 && <table className="mt-2 w-full text-left"><caption className="sr-only">Confidence signals for {field.label}</caption><thead><tr className="text-[10px] uppercase tracking-wide text-slate-400"><th scope="col" className="py-1 font-semibold">Signal</th><th scope="col" className="py-1 text-right font-semibold">Value</th></tr></thead><tbody>
        {signals.map(([name, value]) => <tr key={name} className="border-t border-slate-200"><th scope="row" className="py-1 font-medium capitalize text-slate-600">{signalLabel(name)}</th><td className="py-1 text-right tabular-nums text-slate-800">{value === null ? "n/a" : value.toFixed(2)}</td></tr>)}
      </tbody></table>}
      <p className="mt-2 break-words text-slate-600"><span className="font-semibold text-blue-700">Evidence · page {field.page_number}</span><br />“{field.evidence}”</p>
    </details>
    {canAct && editing && <InlineEditor key={field.id} field={field} saving={saving} error={error} onCancel={onCancelEdit} onSave={onSaveEdit} />}
    {canAct && !editing && <div className="mt-3 flex flex-wrap items-center gap-2">
      {acceptable && <button type="button" className="primary min-h-9 px-3 text-xs" disabled={saving} onClick={onAccept} aria-label={`Accept ${field.label}`}>{saving ? "Saving…" : "Accept"} <kbd className="rounded bg-white/20 px-1 font-mono text-[10px]">↵</kbd></button>}
      <button type="button" className="secondary min-h-9 px-3 text-xs" disabled={saving} onClick={onStartEdit} aria-label={`Edit ${field.label}`}>Edit <kbd className="rounded bg-slate-100 px-1 font-mono text-[10px]">E</kbd></button>
      {error && <span role="alert" className="text-xs font-semibold text-rose-700">{error}</span>}
    </div>}
  </li>;
}
