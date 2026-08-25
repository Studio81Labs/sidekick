import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import AnalyzerRoute from "./AnalyzerRoute";
import type { AnalyzerRouteState } from "./analyzerRouteState";

vi.mock("./AnalyzerPage", () => ({
  default: ({ route }: { route: AnalyzerRouteState }) => (
    <output>
      {route.surface}:{route.jobId ?? "none"}
    </output>
  ),
}));

afterEach(cleanup);

describe("AnalyzerRoute", () => {
  it("passes durable job identity into the analyzer", () => {
    render(
      <MemoryRouter initialEntries={["/analyzer/jobs/job-123"]}>
        <Routes>
          <Route
            path="/analyzer/jobs/:jobId"
            element={<AnalyzerRoute surface="job" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("job:job-123")).toBeInTheDocument();
  });

  it("passes a durable non-job surface without job identity", () => {
    render(
      <MemoryRouter initialEntries={["/analyzer/training"]}>
        <Routes>
          <Route
            path="/analyzer/training"
            element={<AnalyzerRoute surface="training" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("training:none")).toBeInTheDocument();
  });
});
