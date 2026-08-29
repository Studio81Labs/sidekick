import { cleanup, render, screen } from "@testing-library/react";
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
    capabilityEnabled: null,
    checkingCapability: false,
    onCheckCapability: vi.fn(),
    onClose: vi.fn(),
    onLock: vi.fn(),
    onUnlock: vi.fn(() => true),
    unlocked: false,
    ...overrides,
  };
}

describe("AdministrativeAccessDialog", () => {
  it("unlocks with the entered token and never echoes it", async () => {
    const props = dialogProps();
    render(<AdministrativeAccessDialog {...props} />);

    const input = screen.getByLabelText("Administrative OCR test token");
    expect(input).toHaveAttribute("type", "password");
    await userEvent.type(input, "secret-token");
    await userEvent.click(screen.getByRole("button", { name: "Unlock" }));

    expect(props.onUnlock).toHaveBeenCalledWith("secret-token");
  });

  it("explains a blank token instead of unlocking", async () => {
    const props = dialogProps({ onUnlock: vi.fn(() => false) });
    render(<AdministrativeAccessDialog {...props} />);

    await userEvent.click(screen.getByRole("button", { name: "Unlock" }));

    expect(
      screen.getByText("Enter the administrative OCR test token."),
    ).toBeInTheDocument();
  });

  it("offers lock and deployment check once unlocked", async () => {
    const props = dialogProps({ unlocked: true, capabilityEnabled: true });
    render(<AdministrativeAccessDialog {...props} />);

    expect(
      screen.queryByLabelText("Administrative OCR test token"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Enabled on this deployment.")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Lock administrator tools" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Check deployment" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Close administrator tools" }),
    );

    expect(props.onLock).toHaveBeenCalledOnce();
    expect(props.onCheckCapability).toHaveBeenCalledOnce();
    expect(props.onClose).toHaveBeenCalledOnce();
  });

  it("reports a disabled deployment", () => {
    render(
      <AdministrativeAccessDialog
        {...dialogProps({ capabilityEnabled: false })}
      />,
    );

    expect(
      screen.getByText("Disabled on this deployment."),
    ).toBeInTheDocument();
  });
});
