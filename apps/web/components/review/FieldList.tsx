"use client";

import { useEffect, useRef } from "react";
import { FieldRow, type FieldRowProps } from "@/components/review/FieldRow";
import type { FieldDetail } from "@/lib/fields";

type FieldListProps = {
  fields: FieldDetail[];
  focusedIndex: number;
  /** Increments whenever a shortcut asks for focus, so repeated moves to the same index still focus. */
  focusTick: number;
  editingId: string | null;
  savingId: string | null;
  error: { fieldId: string; message: string } | null;
  canAct: boolean;
  highlightedId: string | null;
  onFocusIndex: (index: number) => void;
  onAccept: (field: FieldDetail) => void;
  onStartEdit: (field: FieldDetail) => void;
  onCancelEdit: () => void;
  onSaveEdit: (field: FieldDetail, value: string) => void;
  onFindEvidence: (field: FieldDetail) => void;
};

/** The roving-tabindex list of fields: one row is in the Tab order, J/K move the focus. */
export function FieldList({ fields, focusedIndex, focusTick, editingId, savingId, error, canAct, highlightedId, onFocusIndex, onAccept, onStartEdit, onCancelEdit, onSaveEdit, onFindEvidence }: FieldListProps) {
  const items = useRef<(HTMLLIElement | null)[]>([]);
  useEffect(() => {
    if (focusTick === 0) return;
    const element = items.current[focusedIndex];
    if (!element) return;
    element.focus({ preventScroll: true });
    element.scrollIntoView({ block: "nearest" });
  }, [focusedIndex, focusTick]);

  if (fields.length === 0) return <p className="rounded-2xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">No fields were extracted from this document.</p>;
  const rowProps = (field: FieldDetail, index: number): FieldRowProps => ({
    field,
    index,
    focused: index === (focusedIndex >= 0 && focusedIndex < fields.length ? focusedIndex : 0),
    editing: editingId === field.id,
    saving: savingId === field.id,
    error: error?.fieldId === field.id ? error.message : null,
    canAct,
    highlighted: highlightedId === field.id,
    itemRef: element => { items.current[index] = element; },
    onFocus: () => onFocusIndex(index),
    onAccept: () => onAccept(field),
    onStartEdit: () => onStartEdit(field),
    onCancelEdit,
    onSaveEdit: value => onSaveEdit(field, value),
    onFindEvidence: () => onFindEvidence(field),
  });
  return <ol role="list" aria-label="Extracted fields" className="space-y-3">
    {fields.map((field, index) => <FieldRow key={field.id} {...rowProps(field, index)} />)}
  </ol>;
}
