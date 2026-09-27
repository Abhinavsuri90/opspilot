"use client";

import type { Decision, Workspace } from "./types";

type ReviewDecisionProps = {
  data: Workspace;
  status: string;
  reason: string;
  hasDraft: boolean;
  saving: boolean;
  onReasonChange: (value: string) => void;
  onDecide: (decision: Decision) => void;
};

/** Approve, reject or reopen. Shown only to people the API allows to review. */
export function ReviewDecision({ data, status, reason, hasDraft, saving, onReasonChange, onDecide }: ReviewDecisionProps) {
  if (!data.capabilities.can_review) return null;
  const amountMissing = !data.verified_amount || !data.currency;
  return <div className="rounded-xl border border-cyan-100 bg-cyan-50/60 p-4"><h4 className="text-sm font-bold text-cyan-950">Review decision</h4>{hasDraft && <p className="mt-2 text-xs leading-5 text-amber-900">Save or discard your invoice edits before recording a review decision.</p>}<label className="mt-3 block text-xs font-semibold" htmlFor="review-reason">Decision note (required to reject)</label><textarea id="review-reason" className="field mt-1 text-sm" maxLength={4000} rows={2} value={reason} onChange={event => onReasonChange(event.target.value)} placeholder="What did you check or what needs correcting?" /><div className="mt-3 flex flex-wrap gap-2">{status === "needs_review" ? <><button type="button" className="primary text-sm" disabled={saving || hasDraft || amountMissing} onClick={() => onDecide("approve")}>Approve invoice</button><button type="button" className="secondary text-sm !text-rose-700" disabled={saving || hasDraft || !reason.trim()} onClick={() => onDecide("reject")}>Reject invoice</button></> : (status === "approved" || status === "rejected") ? <button type="button" className="secondary text-sm" disabled={saving || hasDraft} onClick={() => onDecide("reopen")}>Reopen review</button> : <p className="text-xs text-slate-600">Review becomes available after extraction finishes.</p>}</div>{status === "needs_review" && amountMissing && <p className="mt-2 text-xs text-cyan-900">Save a verified amount and currency before approving.</p>}</div>;
}
