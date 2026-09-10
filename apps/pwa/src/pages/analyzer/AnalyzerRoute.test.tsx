import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
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
      <output aria-label="Navigation ownership">
        {navigation.managed ? "route" : "local"}
      </output>
      <button onClick={navigation.openBenchmarks}>Open benchmarks</button>
      <button onClick={() => navigation.openJob("next-job")}>Open job</button>
      <button
        onClick={() => navigation.openJob("replacement-job", { replace: true })}
      >
        Replace job
      </button>
      <button onClick={navigation.closeSurface}>Close surface</button>
    </>
  ),
}));

afterEach(cleanup);

describe("AnalyzerRoute", () => {
  function RouteHarness() {
    const navigate = useNavigate();
    return (
      <>
        <Routes>
          <Route
            path="/admin/ocr"
            element={<AnalyzerRoute surface="workspace" />}
          />
          <Route
            path="/admin/ocr/jobs/:jobId"
            element={<AnalyzerRoute surface="job" />}
          />
          <Route
            path="/admin/ocr/benchmarks"
            element={<AnalyzerRoute surface="benchmarks" />}
          />
        </Routes>
        <output aria-label="Current path">{useLocation().pathname}</output>
        <button onClick={() => navigate(-1)}>Back</button>
      </>
    );
  }

  it("passes durable job identity into the analyzer", () => {
    render(
      <MemoryRouter initialEntries={["/admin/ocr/jobs/job-123"]}>
        <Routes>
          <Route
            path="/admin/ocr/jobs/:jobId"
            element={<AnalyzerRoute surface="job" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("job:job-123")).toBeInTheDocument();
    expect(screen.getByLabelText("Navigation ownership")).toHaveTextContent(
      "route",
    );
  });

  it("passes a durable non-job surface without job identity", () => {
    render(
      <MemoryRouter initialEntries={["/admin/ocr/benchmarks"]}>
        <Routes>
          <Route
            path="/admin/ocr/benchmarks"
            element={<AnalyzerRoute surface="benchmarks" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("benchmarks:none")).toBeInTheDocument();
  });

  it("routes analyzer UI commands through durable URLs", () => {
    render(
      <MemoryRouter initialEntries={["/admin/ocr"]}>
        <RouteHarness />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open benchmarks" }));
    expect(screen.getByText("benchmarks:none")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      "/admin/ocr/benchmarks",
    );

    fireEvent.click(screen.getByRole("button", { name: "Close surface" }));
    expect(screen.getByText("workspace:none")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open job" }));
    expect(screen.getByText("job:next-job")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      "/admin/ocr/jobs/next-job",
    );

    fireEvent.click(screen.getByRole("button", { name: "Open job" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("workspace:none")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open job" }));

    fireEvent.click(screen.getByRole("button", { name: "Replace job" }));
    expect(screen.getByText("job:replacement-job")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("workspace:none")).toBeInTheDocument();
  });

  it("returns a closed surface to its origin without duplicating it", () => {
    render(
      <MemoryRouter
        initialEntries={["/admin/ocr/jobs/prior-job", "/admin/ocr"]}
        initialIndex={1}
      >
        <RouteHarness />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open benchmarks" }));
    fireEvent.click(screen.getByRole("button", { name: "Close surface" }));
    expect(screen.getByText("workspace:none")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("job:prior-job")).toBeInTheDocument();
  });
});
