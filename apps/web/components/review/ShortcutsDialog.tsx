"use client";

import { Dialog } from "@/components/review/Dialog";
import { SHORTCUTS } from "@/lib/review-keys";

/** Every review shortcut in one place, opened with "?" or the toolbar button. */
export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return <Dialog title="Keyboard shortcuts" description="Shortcuts are paused while you type in a field or a dialog is open." onClose={onClose} testId="shortcuts-dialog">
    <dl className="divide-y divide-slate-100">
      {SHORTCUTS.map(item => <div key={item.description} className="flex items-center justify-between gap-4 py-2 text-sm">
        <dt className="text-slate-700">{item.description}</dt>
        <dd className="flex shrink-0 gap-1">{item.keys.map(key => <kbd key={key} className="rounded-md border border-slate-300 bg-slate-50 px-2 py-0.5 font-mono text-xs font-bold text-slate-700">{key}</kbd>)}</dd>
      </div>)}
    </dl>
    <button type="button" className="secondary mt-4 w-full text-sm" onClick={onClose}>Close</button>
  </Dialog>;
}
