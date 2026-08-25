import { describe, expect, it } from "vitest";

import * as presentation from "./benchmarkPresentation";

describe("benchmark presentation compatibility barrel", () => {
  it("keeps the established runtime exports available", () => {
    expect(presentation).toMatchObject({
      benchmarkCaseChanges: expect.any(Function),
      benchmarkComparisonValue: expect.any(Function),
      benchmarkParserRouteSummary: expect.any(Function),
      benchmarkReportSummary: expect.any(Function),
      cacheBenchmarkReport: expect.any(Function),
      loadCachedBenchmarkReport: expect.any(Function),
    });
  });
});
