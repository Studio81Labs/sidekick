import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AdministrativeAccessDialog,
  type AdministrativeAccessDialogProps,
} from "./AdministrativeAccessDialog";

afterEach(cleanup);

function dialogProps(
  overrides: Partial<AdministrativeAccessDialogProps> = {},
): AdministrativeAccessDialogProps {
  return {
    busy: false,
    onClose: vi.fn(),
    onLock: vi.fn(),
    onUnlock: vi.fn(async () => "unlocked" as const),
    unlocked: false,
    verifying: false,
    ...overrides,
  };
}

describe("AdministrativeAccessDialog", () => {
  it("unlocks with the entered token and never echoes it", async () => {
    const props = dialogProps();
    render(<AdministrativeAccessDialog {...props} />);

    expect(
      screen.getByText(
        "The token is verified with the server before any capture control is shown.",
      ),
    ).toBeInTheDocument();
    const input = screen.getByLabelText("Administrative OCR test token");
    expect(input).toHaveAttribute("type", "password");
    await userEvent.type(input, "secret-token");
    await userEvent.click(screen.getByRole("button", { name: "Unlock" }));

    expect(props.onUnlock).toHaveBeenCalledWith("secret-token");
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("explains a blank token instead of asking the server", async () => {
    const props = dialogProps({
      onUnlock: vi.fn(async () => "blank" as const),
    });
    render(<AdministrativeAccessDialog {...props} />);

    await userEvent.click(screen.getByRole("button", { name: "Unlock" }));

    expect(
      await screen.findByText("Enter the administrative OCR test token."),
    ).toBeInTheDocument();
  });

  it.each([
    [
      "unauthorized" as const,
      "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
    ],
    [
      "disabled" as const,
      "Administrative OCR test mode is disabled on this deployment.",
    ],
    [
      "unavailable" as const,
      "Could not verify the administrative OCR test token. Check the connection and try again.",
    ],
  ])(
    "reports a %s verification and keeps the draft",
    async (result, message) => {
      const props = dialogProps({ onUnlock: vi.fn(async () => result) });
      render(<AdministrativeAccessDialog {...props} />);

      const input = screen.getByLabelText("Administrative OCR test token");
      await userEvent.type(input, "secret-token");
      await userEvent.click(screen.getByRole("button", { name: "Unlock" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(message);
      expect(input).toHaveValue("secret-token");
    },
  );

  it("waits for the verification before accepting another attempt", () => {
    render(
      <AdministrativeAccessDialog {...dialogProps({ verifying: true })} />,
    );

    expect(screen.getByRole("button", { name: "Verifying…" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Unlock" }),
    ).not.toBeInTheDocument();
  });

  it("offers lock once unlocked and holds it while a batch runs", async () => {
    const props = dialogProps({ unlocked: true });
    const { rerender } = render(<AdministrativeAccessDialog {...props} />);

    expect(
      screen.queryByLabelText("Administrative OCR test token"),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Lock administrator tools" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Close administrator tools" }),
    );

    expect(props.onLock).toHaveBeenCalledOnce();
    expect(props.onClose).toHaveBeenCalledOnce();

    rerender(
      <AdministrativeAccessDialog
        {...dialogProps({ busy: true, unlocked: true })}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Lock administrator tools" }),
    ).toBeDisabled();
  });
});
