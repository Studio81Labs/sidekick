import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DialogHeader } from "./DialogHeader";

describe("DialogHeader", () => {
  it("links the title and exposes an accessible close action", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <div role="dialog" aria-labelledby="settings-title">
        <DialogHeader
          titleId="settings-title"
          title="Settings"
          subtitle="Configure the analyzer"
          closeLabel="Close settings"
          onClose={onClose}
        />
      </div>,
    );

    expect(screen.getByRole("dialog", { name: "Settings" })).toBeVisible();
    expect(screen.getByText("Configure the analyzer")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Close settings" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("prevents closing while the parent operation is busy", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <DialogHeader
        titleId="restore-title"
        title="Restore"
        subtitle="Importing data"
        closeLabel="Close restore"
        closeDisabled
        onClose={onClose}
      />,
    );

    const closeButton = screen.getByRole("button", { name: "Close restore" });
    expect(closeButton).toBeDisabled();

    await user.click(closeButton);

    expect(onClose).not.toHaveBeenCalled();
  });
});
