"use client";

import Link from "next/link";
import { useState } from "react";
import { DiffPreview } from "@/components/actions/DiffPreview";
import { AttemptLog } from "@/components/actions/AttemptLog";
import { badgeTones } from "@/components/StatusBadge";
import { Dialog } from "@/components/review/Dialog";
import { actionStatusLabel, actionStatusTone, actionTypeLabel, policyModeLabel, RETRYABLE_STATUSES, type ActionSummary } from "@/lib/actions";
import { formatDateTime } from "@/lib/format";

export function ActionStatusBadge({ status }: { status: string }) {
  const tone = actionStatusTone(status);
  return <span data-status={status} data-tone={tone} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold ${badgeTones[tone]}`}>
    <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />{actionStatusLabel(status)}
  </span>;
}

type ActionCardProps = {
  action: ActionSummary;
  /** Whether the signed-in person may approve, reject or retry (reviewer or administrator). */
  canDecide: boolean;
  /** True while the organization's kill switch is engaged, when known. */
  paused?: boolean;
  busy: boolean;
  error: string | null;
  onApprove: (action: ActionSummary) => void;
  onReject: (action: ActionSummary, reason: string) => void;
  onRetry: (action: ActionSummary) => void;
  /** Dead letters show every attempt; history keeps the preview folded. */
  variant: "pending" | "history" | "dead";
};

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="min-w-0"><dt className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</dt><dd className="break-words text-xs text-slate-700">{children}</dd></div>;
}

/** One proposed, running or settled action: what it does, why it is in this state, and the controls the role allows. */
export function ActionCard({ action, canDecide, paused = false, busy, error, onApprove, onReject, onRetry, variant }: ActionCardProps) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const pending = action.status === "proposed";
  const retryable = RETRYABLE_STATUSES.has(action.status);
  const queued = action.status === "approved" || action.status === "retrying";

  function submitReject() {
    if (!reason.trim() || busy) return;
    onReject(action, reason);
    setRejecting(false);
    setReason("");
  }

  return <article aria-label={`${actionTypeLabel(action.action_type)} for ${action.filename}`} data-action-id={action.id} data-status={action.status} className="card min-w-0 p-4 sm:p-5">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <ActionStatusBadge status={action.status} />
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-600">Policy: {policyModeLabel(action.policy_mode)}</span>
        </div>
        <h3 className="mt-2 break-words text-base font-bold capitalize tracking-tight text-slate-900">{actionTypeLabel(action.action_type)} <span className="font-normal normal-case text-slate-500">to</span> <span className="normal-case">{action.destination}</span></h3>
        <p className="mt-0.5 break-all text-sm text-slate-600"><Link href={`/review/${encodeURIComponent(action.document_id)}`} className="font-semibold text-[#11627a] hover:underline">{action.filename}</Link>{action.connector_name && <> · via {action.connector_name}</>}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {pending && canDecide && <>
          <button type="button" className="primary !min-h-10 text-sm" disabled={busy} onClick={() => onApprove(action)}>{busy ? "Working…" : "Approve"}</button>
          <button type="button" className="secondary !min-h-10 text-sm !text-rose-700" disabled={busy} onClick={() => setRejecting(true)} aria-haspopup="dialog">Reject</button>
        </>}
        {retryable && canDecide && <button type="button" className="secondary !min-h-10 text-sm" disabled={busy} onClick={() => onRetry(action)}>{busy ? "Working…" : "Retry"}</button>}
      </div>
    </header>

    {pending && !canDecide && <p className="mt-3 rounded-xl bg-blue-50 p-3 text-xs text-blue-900">Awaiting a reviewer or administrator. You can inspect the preview but not decide it.</p>}
    {queued && paused && <p role="status" className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-semibold text-rose-800">Agent paused: this action stays approved and executes once the kill switch is disengaged.</p>}
    {queued && !paused && action.next_attempt_at && <p className="mt-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-700">Next attempt {formatDateTime(action.next_attempt_at)}.</p>}
    {action.error && <p role="alert" className="mt-3 break-words rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs text-rose-800"><span className="font-bold">Last error:</span> {action.error}</p>}
    {error && <p role="alert" className="mt-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}

    <div className="mt-4"><DiffPreview preview={action.preview} compact={variant !== "pending"} /></div>

    <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
      <Fact label="Proposed">{formatDateTime(action.proposed_at)}</Fact>
      <Fact label="Decided">{action.decided_at ? <>{formatDateTime(action.decided_at)}{action.decided_by_email && <span className="block break-all text-slate-500">{action.decided_by_email}</span>}</> : "—"}</Fact>
      <Fact label="Executed">{action.executed_at ? formatDateTime(action.executed_at) : "—"}</Fact>
      <Fact label="Attempts">{action.attempts}</Fact>
    </dl>
    {action.decision_comment && <p className="mt-3 break-words rounded-xl bg-slate-50 p-3 text-xs text-slate-700"><span className="font-bold">Decision note:</span> {action.decision_comment}</p>}
    {variant !== "pending" && <AttemptLog actionId={action.id} defaultOpen={variant === "dead"} version={action.version} />}

    {rejecting && <Dialog title="Reject this action?" description="The action is recorded as rejected and never executes. Explain why so the audit trail is useful." onClose={() => setRejecting(false)} testId="reject-action-dialog">
      <label htmlFor={`reject-reason-${action.id}`} className="block text-xs font-semibold text-slate-700">Reason</label>
      <textarea id={`reject-reason-${action.id}`} className="field mt-1 text-sm" rows={3} maxLength={4000} value={reason} onChange={event => setReason(event.target.value)} placeholder="Why should this not be sent?" />
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" className="secondary text-sm" onClick={() => setRejecting(false)}>Cancel</button>
        <button type="button" className="rounded-lg bg-rose-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={!reason.trim() || busy} onClick={submitReject}>Reject action</button>
      </div>
    </Dialog>}
  </article>;
}
