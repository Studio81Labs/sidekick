import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { analyzerJobPath, AppRoutes } from "./routes";

vi.mock("../pages/analyzer/AnalyzerRoute", () => ({
  default: ({ surface }: { surface: string }) => <div>Analyzer {surface}</div>,
}));

vi.mock("../pages/mcp/McpAdministrationPage", () => ({
  default: () => <div>Agent access administration</div>,
}));

afterEach(cleanup);

function LocationProbe() {
  return <output aria-label="Current path">{useLocation().pathname}</output>;
}

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("AppRoutes", () => {
  it("redirects the root to the administrator OCR entry point", async () => {
    renderRoute("/");

    expect(await screen.findByText("Analyzer workspace")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      "/admin/ocr",
    );
  });

  it("renders the durable administrator workspace", () => {
    renderRoute("/admin/ocr");

    expect(screen.getByText("Analyzer workspace")).toBeInTheDocument();
  });

  it.each([
    ["job", "/admin/ocr/jobs/job-123"],
    ["benchmarks", "/admin/ocr/benchmarks"],
  ])("renders the durable %s surface", (surface, path) => {
    renderRoute(path);

    expect(screen.getByText(`Analyzer ${surface}`)).toBeInTheDocument();
  });

  it("keeps MCP credential administration outside the OCR test-mode gate", () => {
    renderRoute("/admin/ocr/mcp");

    expect(screen.getByText("Agent access administration")).toBeInTheDocument();
  });

  it("builds encoded durable job paths", () => {
    expect(analyzerJobPath("job / 123")).toBe(
      "/admin/ocr/jobs/job%20%2F%20123",
    );
  });

  it("does not redirect unknown or removed analyzer paths", () => {
    renderRoute("/future-account-page");

    expect(screen.getByText("Page not found")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      "/future-account-page",
    );
    cleanup();
    renderRoute("/analyzer");
    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });
});
