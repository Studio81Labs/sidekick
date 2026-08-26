import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DialogFooter } from "./DialogFooter";

describe("DialogFooter", () => {
  it("applies the shared footer class and preserves custom classes", () => {
    render(
      <DialogFooter className="settings-footer" data-testid="dialog-footer">
        <button type="button">Done</button>
      </DialogFooter>,
    );

    const footer = screen.getByTestId("dialog-footer");
    expect(footer).toHaveClass("automation-dialog-footer", "settings-footer");
    expect(screen.getByRole("button", { name: "Done" })).toBeVisible();
  });

  it("forwards native div attributes", () => {
    render(
      <DialogFooter aria-label="Benchmark actions" aria-live="polite">
        Ready
      </DialogFooter>,
    );

    const footer = screen.getByLabelText("Benchmark actions");
    expect(footer).toHaveAttribute("aria-live", "polite");
    expect(footer).toHaveTextContent("Ready");
  });
});
