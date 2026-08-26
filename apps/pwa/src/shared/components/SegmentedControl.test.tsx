import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SegmentedControl } from "./SegmentedControl";

afterEach(cleanup);

const OPTIONS = [
  { value: "live", label: "Live" },
  { value: "upload", label: "Upload" },
] as const;

describe("SegmentedControl", () => {
  it("renders the selected option and reports a new selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <SegmentedControl
        ariaLabel="Input mode"
        className="input-mode-switch"
        options={OPTIONS}
        value="live"
        onChange={onChange}
      />,
    );

    const group = screen.getByRole("group", { name: "Input mode" });
    expect(group).toHaveClass("input-mode-switch");
    expect(screen.getByRole("button", { name: "Live" })).toHaveClass(
      "button-control",
      "unstyled-button",
      "active",
    );
    expect(screen.getByRole("button", { name: "Live" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Upload" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(onChange).toHaveBeenCalledWith("upload");
  });

  it("forwards group and option disabled states", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    const { rerender } = render(
      <SegmentedControl
        ariaLabel="Input mode"
        disabled
        options={OPTIONS}
        value="live"
        onChange={onChange}
      />,
    );

    expect(screen.getByRole("button", { name: "Live" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();

    rerender(
      <SegmentedControl
        ariaLabel="Input mode"
        options={[OPTIONS[0], { ...OPTIONS[1], disabled: true }]}
        value="live"
        onChange={onChange}
      />,
    );

    expect(screen.getByRole("button", { name: "Live" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("reports clicks on the selected option so consumers may clear it", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <SegmentedControl
        ariaLabel="How sure are you?"
        options={[
          { value: "low", label: "low" },
          { value: "high", label: "high" },
        ]}
        value="high"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "high" }));
    expect(onChange).toHaveBeenCalledWith("high");
  });
});
