import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { analyzerJobPath, AppRoutes } from "./routes";

vi.mock("../pages/analyzer/AnalyzerRoute", () => ({
  default: ({ surface }: { surface: string }) => <div>Analyzer {surface}</div>,
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
  it("redirects the compatibility root to the analyzer", async () => {
    renderRoute("/");

    expect(await screen.findByText("Analyzer workspace")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      "/analyzer",
    );
  });

  it("renders the durable analyzer workspace", () => {
    renderRoute("/analyzer");

    expect(screen.getByText("Analyzer workspace")).toBeInTheDocument();
  });

  it.each([
    ["job", "/analyzer/jobs/job-123"],
    ["training", "/analyzer/training"],
    ["benchmarks", "/analyzer/benchmarks"],
  ])("renders the durable %s surface", (surface, path) => {
    renderRoute(path);

    expect(screen.getByText(`Analyzer ${surface}`)).toBeInTheDocument();
  });

  it("builds encoded durable job paths", () => {
    expect(analyzerJobPath("job / 123")).toBe("/analyzer/jobs/job%20%2F%20123");
  });

  it("returns unknown paths to the analyzer", async () => {
    renderRoute("/future-account-page");

    expect(await screen.findByText("Analyzer workspace")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      "/analyzer",
    );
  });
});
