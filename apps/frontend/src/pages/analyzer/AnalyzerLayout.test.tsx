import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  AnalyzerControlRail,
  AnalyzerDialogHost,
  AnalyzerLayout,
  AnalyzerWorkspaceLayout,
} from "./AnalyzerLayout";

afterEach(cleanup);

describe("AnalyzerLayout", () => {
  it("composes the workspace landmarks and dialog layer in page order", () => {
    render(
      <AnalyzerLayout>
        <header>Analyzer toolbar</header>
        <AnalyzerWorkspaceLayout>
          <AnalyzerControlRail>
            <div>Capture controls</div>
            <div>Queue controls</div>
            <div>History controls</div>
          </AnalyzerControlRail>
          <div>Table preview</div>
          <div>Review workspace</div>
        </AnalyzerWorkspaceLayout>
        <AnalyzerDialogHost>
          <div role="dialog">Analyzer dialog</div>
        </AnalyzerDialogHost>
      </AnalyzerLayout>,
    );

    const shell = screen.getByText("Analyzer toolbar").closest("main");
    const workspace = screen.getByText("Table preview").closest("section");
    const controlRail = screen.getByRole("complementary", {
      name: "Capture, queue and history",
    });

    expect(shell).toHaveClass("app-shell");
    expect(workspace).toHaveClass("app-workspace");
    expect(controlRail).toHaveClass("control-rail");
    expect(controlRail).toHaveTextContent("Capture controls");
    expect(controlRail).toHaveTextContent("Queue controls");
    expect(controlRail).toHaveTextContent("History controls");
    expect(screen.getByRole("dialog")).toHaveTextContent("Analyzer dialog");
  });
});
