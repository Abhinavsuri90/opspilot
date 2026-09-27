import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KillSwitchDialog } from "./KillSwitchDialog";

describe("KillSwitchDialog", () => {
  it("asks before pausing and only confirms on the explicit button", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<KillSwitchDialog engaging saving={false} onConfirm={onConfirm} onClose={onClose} />);
    const dialog = screen.getByRole("dialog", { name: "Pause the agent?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent(/no action executes, including ones already approved/);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Pause agent" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("uses resume wording when disengaging and closes on Escape", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<KillSwitchDialog engaging={false} saving={false} onConfirm={onConfirm} onClose={onClose} />);
    const dialog = screen.getByRole("dialog", { name: "Resume the agent?" });
    expect(screen.getByRole("button", { name: "Resume agent" })).toBeEnabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disables both buttons while saving and shows the API's error", () => {
    render(<KillSwitchDialog engaging saving error="Settings changed. Refresh them before saving again." onConfirm={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Settings changed");
  });
});
