"use client";

import { Dialog } from "@/components/review/Dialog";

type KillSwitchDialogProps = {
  /** True when the switch is about to be engaged (agent paused), false when releasing it. */
  engaging: boolean;
  saving: boolean;
  error?: string | null;
  onConfirm: () => void;
  onClose: () => void;
};

export const killSwitchCopy = {
  engage: {
    title: "Pause the agent?",
    description: "While the kill switch is engaged no action executes, including ones already approved. They wait and resume automatically when you disengage it. Everyone in the organization sees an “Agent paused” banner.",
    confirm: "Pause agent",
  },
  disengage: {
    title: "Resume the agent?",
    description: "Approved actions that were waiting execute again within about a minute, under the policies configured for each action type.",
    confirm: "Resume agent",
  },
} as const;

/** The kill switch is the emergency brake, so flipping it either way asks first. */
export function KillSwitchDialog({ engaging, saving, error, onConfirm, onClose }: KillSwitchDialogProps) {
  const copy = engaging ? killSwitchCopy.engage : killSwitchCopy.disengage;
  return <Dialog title={copy.title} description={copy.description} onClose={onClose} testId="kill-switch-dialog">
    {error && <p role="alert" className="mb-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    <div className="flex flex-wrap justify-end gap-2">
      <button type="button" className="secondary text-sm" onClick={onClose} disabled={saving}>Cancel</button>
      <button type="button" className={`rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 ${engaging ? "bg-rose-700 hover:bg-rose-800" : "bg-emerald-700 hover:bg-emerald-800"}`} onClick={onConfirm} disabled={saving}>{saving ? "Saving…" : copy.confirm}</button>
    </div>
  </Dialog>;
}
