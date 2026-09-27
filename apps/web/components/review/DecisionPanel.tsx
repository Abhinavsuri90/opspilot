"use client";

import type { RefObject } from "react";

type DecisionPanelProps = {
  status: string;
  canReview: boolean;
  flaggedCount: number;
  reason: string;
  saving: boolean;
  error: string | null;
  reasonRef: RefObject<HTMLTextAreaElement | null>;
  onReasonChange: (value: string) => void;
  onApprove: () => void;
  onReject: () => void;
  onReopen: () => void;
};

const COMPLETED = new Set(["approved", "rejected", "auto_approved"]);

/** Approve (after every flagged field is resolved), reject with a reason, or reopen a finished review. */
export function DecisionPanel({ status, canReview, flaggedCount, reason, saving, error, reasonRef, onReasonChange, onApprove, onReject, onReopen }: DecisionPanelProps) {
  const awaiting = status === "needs_review";
  const blocked = flaggedCount > 0;
  return <section aria-label="Review decision" className="rounded-2xl border border-cyan-100 bg-cyan-50/60 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-bold text-cyan-950">Review decision</h3><span className="text-[11px] font-semibold text-cyan-900/70">Keys: A approve · R reject note</span></div>
    {!canReview && <p className="mt-2 text-sm text-cyan-900">You can inspect this invoice, but recording a decision needs an admin or the assigned reviewer.</p>}
    {canReview && <>
      <label className="mt-3 block text-xs font-semibold text-slate-700" htmlFor="review-reason">Decision note (required to reject)</label>
      <textarea id="review-reason" ref={reasonRef} className="field mt-1 text-sm" maxLength={4000} rows={2} value={reason} onChange={event => onReasonChange(event.target.value)} placeholder="What did you check or what needs correcting?" disabled={saving} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {awaiting && <>
          <button type="button" className="primary text-sm" disabled={saving || blocked} onClick={onApprove} aria-describedby={blocked ? "approve-blocked" : undefined}>Approve invoice</button>
          <button type="button" className="secondary text-sm !text-rose-700" disabled={saving || !reason.trim()} onClick={onReject}>Reject invoice</button>
          {blocked && <span id="approve-blocked" className="text-xs font-semibold text-amber-900">{flaggedCount} field(s) still need review</span>}
        </>}
        {COMPLETED.has(status) && <button type="button" className="secondary text-sm" disabled={saving} onClick={onReopen}>Reopen review</button>}
        {!awaiting && !COMPLETED.has(status) && <p className="text-xs text-slate-600">Review becomes available after extraction finishes.</p>}
      </div>
      {awaiting && !blocked && <p className="mt-2 text-xs text-cyan-900">Approval uses the verified amount and currency, or derives them from the total and currency fields.</p>}
    </>}
    {error && <p role="alert" className="mt-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
  </section>;
}
