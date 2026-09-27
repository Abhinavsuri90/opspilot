import { describe, expect, it } from "vitest";
import { reviewShortcut, type KeyContext, type KeyState } from "./review-keys";

const base: KeyContext = { key: "", inEditable: false, onControl: false, dialogOpen: false };
const state: KeyState = { focusedIndex: 1, fieldCount: 4 };
const press = (key: string, overrides: Partial<KeyContext> = {}, current: KeyState = state) => reviewShortcut({ ...base, key, ...overrides }, current);

describe("review shortcuts", () => {
  it("moves the focused field with J/K and the arrow keys, clamped to the list", () => {
    expect(press("j")).toEqual({ type: "move", index: 2 });
    expect(press("J")).toEqual({ type: "move", index: 2 });
    expect(press("ArrowDown")).toEqual({ type: "move", index: 2 });
    expect(press("k")).toEqual({ type: "move", index: 0 });
    expect(press("ArrowUp")).toEqual({ type: "move", index: 0 });
    expect(press("j", {}, { focusedIndex: 3, fieldCount: 4 })).toEqual({ type: "move", index: 3 });
    expect(press("k", {}, { focusedIndex: 0, fieldCount: 4 })).toEqual({ type: "move", index: 0 });
  });

  it("starts at the first field when nothing is focused yet", () => {
    expect(press("j", {}, { focusedIndex: -1, fieldCount: 4 })).toEqual({ type: "move", index: 0 });
    expect(press("k", {}, { focusedIndex: -1, fieldCount: 4 })).toEqual({ type: "move", index: 0 });
    expect(press("j", {}, { focusedIndex: -1, fieldCount: 0 })).toEqual({ type: "none" });
  });

  it("accepts and edits only a focused field", () => {
    expect(press("Enter")).toEqual({ type: "accept", index: 1 });
    expect(press("e")).toEqual({ type: "edit", index: 1 });
    expect(press("E")).toEqual({ type: "edit", index: 1 });
    expect(press("Enter", {}, { focusedIndex: -1, fieldCount: 4 })).toEqual({ type: "none" });
    expect(press("e", {}, { focusedIndex: 9, fieldCount: 4 })).toEqual({ type: "none" });
  });

  it("leaves Enter to a focused button or link so it is not also an accept", () => {
    expect(press("Enter", { onControl: true })).toEqual({ type: "none" });
    expect(press("j", { onControl: true })).toEqual({ type: "move", index: 2 });
  });

  it("maps the decision and help keys", () => {
    expect(press("a")).toEqual({ type: "approve" });
    expect(press("A")).toEqual({ type: "approve" });
    expect(press("r")).toEqual({ type: "reject" });
    expect(press("?")).toEqual({ type: "toggle-shortcuts" });
    expect(press("x")).toEqual({ type: "none" });
  });

  it("cancels an open edit with Escape once focus has left the editor", () => {
    expect(press("Escape")).toEqual({ type: "cancel-edit" });
    expect(press("Escape", { onControl: true })).toEqual({ type: "cancel-edit" });
    expect(press("Escape", { inEditable: true })).toEqual({ type: "none" });
  });

  it("ignores every key while typing in a form control", () => {
    for (const key of ["j", "k", "Enter", "e", "a", "r", "?"]) {
      expect(press(key, { inEditable: true })).toEqual({ type: "none" });
    }
  });

  it("ignores browser shortcuts that use a modifier", () => {
    expect(press("a", { modifier: true })).toEqual({ type: "none" });
    expect(press("j", { modifier: true })).toEqual({ type: "none" });
  });

  it("only lets Escape through while a dialog is open", () => {
    for (const key of ["j", "k", "Enter", "e", "a", "r", "?"]) {
      expect(press(key, { dialogOpen: true })).toEqual({ type: "none" });
    }
    expect(press("Escape", { dialogOpen: true })).toEqual({ type: "close-dialog" });
    expect(press("Escape", { dialogOpen: true, inEditable: true })).toEqual({ type: "close-dialog" });
  });
});
