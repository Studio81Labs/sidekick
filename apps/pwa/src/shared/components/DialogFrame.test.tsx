import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DialogFrame } from "./DialogFrame";

describe("DialogFrame", () => {
  it("renders a labelled modal inside the shared backdrop", () => {
    render(
      <DialogFrame
        titleId="settings-title"
        className="settings-dialog"
        data-testid="settings-dialog"
      >
        <h2 id="settings-title">Settings</h2>
      </DialogFrame>,
    );

    const dialog = screen.getByRole("dialog", { name: "Settings" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveClass("automation-dialog", "settings-dialog");
    expect(dialog.parentElement).toHaveClass("modal-backdrop");
    expect(dialog).toHaveAttribute("data-testid", "settings-dialog");
  });

  it("forwards its ref to the dialog element", () => {
    const dialogRef = createRef<HTMLDivElement>();

    render(
      <DialogFrame ref={dialogRef} titleId="guide-title">
        <h2 id="guide-title">Guide</h2>
      </DialogFrame>,
    );

    expect(dialogRef.current).toBe(
      screen.getByRole("dialog", { name: "Guide" }),
    );
  });
});
