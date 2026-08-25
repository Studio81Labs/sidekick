import { describe, expect, it } from "vitest";

import { analyzerRouteState } from "./AnalyzerRoute";

describe("analyzerRouteState", () => {
  it("keeps job identity only on the durable job surface", () => {
    expect(analyzerRouteState("job", "job-123")).toEqual({
      jobId: "job-123",
      surface: "job",
    });
    expect(analyzerRouteState("workspace", "job-123")).toEqual({
      jobId: null,
      surface: "workspace",
    });
  });

  it("represents a missing job parameter explicitly", () => {
    expect(analyzerRouteState("job")).toEqual({
      jobId: null,
      surface: "job",
    });
  });
});
