// Keyboard handling for the review split view, kept free of React so every
// rule can be unit tested: which key does what, and when keys are ignored.

export type ShortcutAction =
  | { type: "move"; index: number }
  | { type: "accept"; index: number }
  | { type: "edit"; index: number }
  | { type: "approve" }
  | { type: "reject" }
  | { type: "toggle-shortcuts" }
  | { type: "close-dialog" }
  | { type: "cancel-edit" }
  | { type: "none" };

export type KeyContext = {
  key: string;
  /** Ctrl, Meta or Alt is held: leave browser and OS shortcuts alone. */
  modifier?: boolean;
  /** Focus is inside an input, textarea, select or contenteditable element. */
  inEditable: boolean;
  /** Focus is on a button, link or summary, where Enter and Space activate it. */
  onControl: boolean;
  dialogOpen: boolean;
};

export type KeyState = { focusedIndex: number; fieldCount: number };

export const SHORTCUTS: { keys: string[]; description: string }[] = [
  { keys: ["J", "↓"], description: "Focus the next field" },
  { keys: ["K", "↑"], description: "Focus the previous field" },
  { keys: ["Enter"], description: "Accept the focused field" },
  { keys: ["E"], description: "Edit the focused field" },
  { keys: ["A"], description: "Approve the invoice (asks to confirm)" },
  { keys: ["R"], description: "Reject: jump to the decision note" },
  { keys: ["?"], description: "Show or hide these shortcuts" },
  { keys: ["Esc"], description: "Close a dialog or cancel an edit" },
];

const EDITABLE_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);
const CONTROL_TAGS = new Set(["BUTTON", "A", "SUMMARY"]);

export function isEditableElement(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return EDITABLE_TAGS.has(target.tagName) || target.isContentEditable;
}

export function isControlElement(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return CONTROL_TAGS.has(target.tagName) || target.getAttribute("role") === "button";
}

/** Reads what the reducer needs from a DOM keyboard event. */
export function keyContext(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "target">, dialogOpen: boolean): KeyContext {
  return {
    key: event.key,
    modifier: event.ctrlKey || event.metaKey || event.altKey,
    inEditable: isEditableElement(event.target),
    onControl: isControlElement(event.target),
    dialogOpen,
  };
}

function clamp(index: number, count: number): number {
  return Math.min(Math.max(index, 0), Math.max(count - 1, 0));
}

/**
 * The single decision point for review shortcuts. Typing never triggers a
 * shortcut, an open dialog swallows everything except Escape, and Escape
 * outside a dialog cancels whatever inline edit is open.
 */
export function reviewShortcut(context: KeyContext, state: KeyState): ShortcutAction {
  if (context.modifier) return { type: "none" };
  if (context.dialogOpen) return context.key === "Escape" ? { type: "close-dialog" } : { type: "none" };
  if (context.inEditable) return { type: "none" };
  const hasFields = state.fieldCount > 0;
  const focused = state.focusedIndex >= 0 && state.focusedIndex < state.fieldCount;
  switch (context.key) {
    case "j": case "J": case "ArrowDown":
      return hasFields ? { type: "move", index: focused ? clamp(state.focusedIndex + 1, state.fieldCount) : 0 } : { type: "none" };
    case "k": case "K": case "ArrowUp":
      return hasFields ? { type: "move", index: focused ? clamp(state.focusedIndex - 1, state.fieldCount) : 0 } : { type: "none" };
    case "Enter":
      return focused && !context.onControl ? { type: "accept", index: state.focusedIndex } : { type: "none" };
    case "e": case "E":
      return focused ? { type: "edit", index: state.focusedIndex } : { type: "none" };
    case "a": case "A":
      return { type: "approve" };
    case "r": case "R":
      return { type: "reject" };
    case "?":
      return { type: "toggle-shortcuts" };
    case "Escape":
      return { type: "cancel-edit" };
    default:
      return { type: "none" };
  }
}
