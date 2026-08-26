import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalyzerToolbar, type AnalyzerToolbarProps } from "./AnalyzerToolbar";

afterEach(cleanup);

function toolbarProps(
  overrides: Partial<AnalyzerToolbarProps> = {},
): AnalyzerToolbarProps {
  return {
    automationEnabled: true,
    busy: false,
    historyTotal: 7,
    liveStatusLabel: "Live capture",
    onConfigureAutomation: vi.fn(),
    onConfigurePipeline: vi.fn(),
    onOpenBenchmark: vi.fn(),
    onOpenHelp: vi.fn(),
    onOpenInfo: vi.fn(),
    onOpenTraining: vi.fn(),
    onToggleAutomation: vi.fn(),
    queueCount: 3,
    screenSharing: true,
    ...overrides,
  };
}

describe("AnalyzerToolbar", () => {
  it("renders session state and delegates every toolbar command", async () => {
    const props = toolbarProps();
    render(<AnalyzerToolbar {...props} />);

    expect(
      screen.getByRole("heading", { name: "Poker Training Analyzer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Post-hand review for Texas Hold'em screenshots"),
    ).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(
      screen.getByText("Live capture").closest(".source-status"),
    ).toHaveClass("active");
    expect(
      screen.getByRole("button", { name: "Automation On" }),
    ).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(
      screen.getByRole("button", { name: "Automation On" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Configure automation" }),
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
      screen.getByRole("button", { name: "Training progress" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Parser benchmark" }),
    );

    expect(props.onToggleAutomation).toHaveBeenCalledOnce();
    expect(props.onConfigureAutomation).toHaveBeenCalledOnce();
    expect(props.onConfigurePipeline).toHaveBeenCalledOnce();
    expect(props.onOpenHelp).toHaveBeenCalledOnce();
    expect(props.onOpenInfo).toHaveBeenCalledOnce();
    expect(props.onOpenTraining).toHaveBeenCalledOnce();
    expect(props.onOpenBenchmark).toHaveBeenCalledOnce();
  });

  it("renders inactive states and locks commands that depend on backend work", () => {
    render(
      <AnalyzerToolbar
        {...toolbarProps({
          automationEnabled: false,
          busy: true,
          liveStatusLabel: "Live capture off",
          screenSharing: false,
        })}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Automation Off" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByText("Live capture off").closest(".source-status"),
    ).not.toHaveClass("active");
    expect(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Training progress" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Parser benchmark" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Configure automation" }),
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
