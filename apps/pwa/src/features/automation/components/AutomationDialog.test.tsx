import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AutomationDialog,
  type AutomationDialogProps,
} from "./AutomationDialog";

afterEach(cleanup);

function dialogProps(
  overrides: Partial<AutomationDialogProps> = {},
): AutomationDialogProps {
  return {
    allowWarnings: false,
    autoApprove: true,
    autoRecommend: true,
    enabled: true,
    onAllowWarningsChange: vi.fn(),
    onAutoApproveChange: vi.fn(),
    onAutoRecommendChange: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
}

describe("AutomationDialog", () => {
  it("renders controlled settings and delegates requested changes", async () => {
    const props = dialogProps();
    render(<AutomationDialog {...props} />);

    expect(
      screen.getByRole("dialog", { name: "Configure automation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: /Auto-approve parsed state/ }),
    ).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByRole("switch", { name: /Auto-request recommendation/ }),
    ).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByRole("switch", { name: /Allow parser warnings/ }),
    ).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("On")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("switch", { name: /Auto-approve parsed state/ }),
    );
    await userEvent.click(
      screen.getByRole("switch", { name: /Auto-request recommendation/ }),
    );
    await userEvent.click(
      screen.getByRole("switch", { name: /Allow parser warnings/ }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Close automation settings" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(props.onAutoApproveChange).toHaveBeenCalledWith(false);
    expect(props.onAutoRecommendChange).toHaveBeenCalledWith(false);
    expect(props.onAllowWarningsChange).toHaveBeenCalledWith(true);
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("locks dependent settings when auto-approval is off", () => {
    render(
      <AutomationDialog
        {...dialogProps({
          allowWarnings: true,
          autoApprove: false,
          autoRecommend: false,
          enabled: false,
        })}
      />,
    );

    expect(
      screen.getByRole("switch", { name: /Auto-approve parsed state/ }),
    ).toBeEnabled();
    expect(
      screen.getByRole("switch", { name: /Auto-request recommendation/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("switch", { name: /Allow parser warnings/ }),
    ).toBeDisabled();
    expect(screen.getByText("Off")).toBeInTheDocument();
  });
});
