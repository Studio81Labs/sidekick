import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToggleControl } from "./ToggleControl";

afterEach(cleanup);

describe("ToggleControl", () => {
  it("renders a checked switch and forwards its click handler", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    render(
      <ToggleControl
        checked
        title="Auto-approve parsed state"
        description="Skip manual review when confidence is high"
        onClick={onClick}
      />,
    );

    const toggle = screen.getByRole("switch", {
      name: /Auto-approve parsed state\s*Skip manual review/i,
    });
    expect(toggle).toHaveClass(
      "button-control",
      "unstyled-button",
      "toggle-control",
    );
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toHaveAttribute("type", "button");
    expect(toggle.querySelector(".switch-control")).toHaveClass("active");

    await user.click(toggle);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("forwards disabled state and custom row classes", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    render(
      <ToggleControl
        checked={false}
        className="benchmark-ground-truth"
        title="Use current hand as ground truth"
        description="Approve the current hand first"
        disabled
        onClick={onClick}
      />,
    );

    const toggle = screen.getByRole("switch", {
      name: /Use current hand as ground truth/i,
    });
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveClass("toggle-control", "benchmark-ground-truth");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle.querySelector(".switch-control")).not.toHaveClass("active");

    await user.click(toggle);
    expect(onClick).not.toHaveBeenCalled();
  });
});
