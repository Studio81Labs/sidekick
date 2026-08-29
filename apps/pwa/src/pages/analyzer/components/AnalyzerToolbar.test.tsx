import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalyzerToolbar, type AnalyzerToolbarProps } from "./AnalyzerToolbar";

afterEach(cleanup);

function toolbarProps(
  overrides: Partial<AnalyzerToolbarProps> = {},
): AnalyzerToolbarProps {
  return {
    administrativeUnlocked: false,
    busy: false,
    historyTotal: 7,
    onConfigurePipeline: vi.fn(),
    onOpenAdministrativeTools: vi.fn(),
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
      screen.getByRole("heading", { name: "Poker Training Analyzer" }),
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
      screen.getByRole("button", { name: "Administrator tools" }),
    ).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(
      screen.getByRole("button", { name: "Administrator tools" }),
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

    expect(props.onOpenAdministrativeTools).toHaveBeenCalledOnce();
    expect(props.onConfigurePipeline).toHaveBeenCalledOnce();
    expect(props.onOpenHelp).toHaveBeenCalledOnce();
    expect(props.onOpenInfo).toHaveBeenCalledOnce();
    expect(props.onOpenBenchmark).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("button", { name: "Training progress" }),
    ).not.toBeInTheDocument();
  });

  it("marks the administrator tools button while the session is unlocked", () => {
    render(
      <AnalyzerToolbar {...toolbarProps({ administrativeUnlocked: true })} />,
    );

    const button = screen.getByRole("button", { name: "Administrator tools" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveClass("active");
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
      screen.getByRole("button", { name: "Administrator tools" }),
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
