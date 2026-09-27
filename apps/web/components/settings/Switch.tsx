"use client";

import { useId, type ReactNode } from "react";

type SwitchProps = {
  label: string;
  description?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  /** The kill switch is red when engaged; ordinary switches are teal. */
  tone?: "default" | "danger";
  onChange: (checked: boolean) => void;
  /** Extra content beside the label, such as an “engaged” pill. */
  badge?: ReactNode;
};

/** An accessible on/off control: a real button with role switch, big enough for a thumb. */
export function Switch({ label, description, checked, disabled = false, tone = "default", onChange, badge }: SwitchProps) {
  const labelId = useId();
  const descriptionId = useId();
  const onColor = tone === "danger" ? "bg-rose-600" : "bg-[#11627a]";
  return <div className="flex items-start justify-between gap-4">
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2"><span id={labelId} className="text-sm font-bold text-slate-900">{label}</span>{badge}</div>
      {description && <div id={descriptionId} className="mt-1 text-xs leading-5 text-slate-600">{description}</div>}
    </div>
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelId}
      aria-describedby={description ? descriptionId : undefined}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#76a2f5] ${checked ? onColor : "bg-slate-300"} ${disabled ? "opacity-60" : ""}`}
    >
      <span aria-hidden="true" className={`inline-block h-6 w-6 transform rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0"}`} />
    </button>
  </div>;
}
