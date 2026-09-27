"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

type DialogProps = {
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  /** Testing hook and stable anchor for the review page. */
  testId?: string;
};

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** A modal that keeps Tab inside it, closes on Escape or backdrop click, and returns focus where it came from. */
export function Dialog({ title, description, onClose, children, testId }: DialogProps) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel.current)?.focus();
    return () => previous?.focus();
  }, []);

  function trapFocus(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !panel.current) return;
    const focusable = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/50 p-4" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div
      ref={panel}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      tabIndex={-1}
      data-testid={testId}
      onKeyDown={trapFocus}
      className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl outline-none"
    >
      <h2 id={titleId} className="text-lg font-bold text-slate-900">{title}</h2>
      {description && <p id={descriptionId} className="mt-1 text-sm text-slate-600">{description}</p>}
      <div className="mt-4">{children}</div>
    </div>
  </div>;
}
