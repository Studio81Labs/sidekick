import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalyzerToolbar, type AnalyzerToolbarProps } from "./AnalyzerToolbar";

afterEach(cleanup);

function toolbarProps(
  overrides: Partial<AnalyzerToolbarProps> = {},
): AnalyzerToolbarProps {
  return {
    busy: false,
    historyTotal: 7,
    onConfigurePipeline: vi.fn(),
    onLockAdministrator: vi.fn(),
    onOpenBenchmark: vi.fn(),
    onOpenHelp: vi.fn(),
    onOpenInfo: vi.fn(),
    queueCount: 3,
    ...overrides,
  };
}

describe("AnalyzerToolbar", () => {
  it("renders session state and delegates every toolbar command", async () => {
    const props = toolbarProps();
    const { container } = render(<AnalyzerToolbar {...props} />);

    expect(
      screen.getByRole("heading", { name: "Poker Hero" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Administrator OCR test console for Texas Hold'em screenshots",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(container.querySelector(".source-status")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Automation/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Lock administrator session" }),
    ).toHaveClass("active");

    await userEvent.click(
      screen.getByRole("button", { name: "Lock administrator session" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: "How to use Poker Training Analyzer",
      }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "About this app" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Parser benchmark" }),
    );

    expect(props.onLockAdministrator).toHaveBeenCalledOnce();
    expect(props.onConfigurePipeline).toHaveBeenCalledOnce();
    expect(props.onOpenHelp).toHaveBeenCalledOnce();
    expect(props.onOpenInfo).toHaveBeenCalledOnce();
    expect(props.onOpenBenchmark).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("button", { name: "Training progress" }),
    ).not.toBeInTheDocument();
  });

  it("renders inactive states and locks commands that depend on backend work", () => {
    render(<AnalyzerToolbar {...toolbarProps({ busy: true })} />);

    expect(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Parser benchmark" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Lock administrator session" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "How to use Poker Training Analyzer",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "About this app" }),
    ).toBeEnabled();
  });
});
