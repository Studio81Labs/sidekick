import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import AnalyzerRoute from "./AnalyzerRoute";
import type {
  AnalyzerRouteNavigation,
  AnalyzerRouteState,
} from "./analyzerRouteState";

vi.mock("./AnalyzerPage", () => ({
  default: ({
    navigation,
    route,
  }: {
    navigation: AnalyzerRouteNavigation;
    route: AnalyzerRouteState;
  }) => (
    <>
      <output>{`${route.surface}:${route.jobId ?? "none"}`}</output>
      <button onClick={navigation.openTraining}>Open training</button>
      <button onClick={() => navigation.openJob("next-job")}>Open job</button>
      <button onClick={navigation.openWorkspace}>Close surface</button>
    </>
  ),
}));

afterEach(cleanup);

describe("AnalyzerRoute", () => {
  function RouteHarness() {
    return (
      <>
        <Routes>
          <Route
            path="/analyzer"
            element={<AnalyzerRoute surface="workspace" />}
          />
          <Route
            path="/analyzer/jobs/:jobId"
            element={<AnalyzerRoute surface="job" />}
          />
          <Route
            path="/analyzer/training"
            element={<AnalyzerRoute surface="training" />}
          />
        </Routes>
        <output aria-label="Current path">{useLocation().pathname}</output>
      </>
    );
  }

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

  it("routes analyzer UI commands through durable URLs", () => {
    render(
      <MemoryRouter initialEntries={["/analyzer"]}>
        <RouteHarness />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open training" }));
    expect(screen.getByText("training:none")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      "/analyzer/training",
    );

    fireEvent.click(screen.getByRole("button", { name: "Close surface" }));
    expect(screen.getByText("workspace:none")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open job" }));
    expect(screen.getByText("job:next-job")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      "/analyzer/jobs/next-job",
    );
  });
});
