import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { runParserBenchmarkCommand } from "./runParserBenchmarkCommand";

afterEach(resetApiMocks);

describe("run parser benchmark command", () => {
  it("returns the report and invalidates benchmark overview state", async () => {
    const queryClient = createQueryClient();
    const overviewKey = benchmarkQueryKeys.overview();
    const report = { id: "benchmark-1", included_cases: 2 };
    queryClient.setQueryData(overviewKey, { included_cases: 1 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(report)));

    const outcome = await runParserBenchmarkCommand(queryClient, {
      pipeline: {
        parser_provider: "ocr_cv",
        parser_layout_profile: "fortuna_nations",
      },
    });

    expect(outcome).toEqual({
      report,
      cache: { invalidated: [benchmarkQueryKeys.overviews()] },
    });
    expect(queryClient.getQueryState(overviewKey)?.isInvalidated).toBe(true);
  });

  it("leaves Query state untouched when benchmark transport fails", async () => {
    const queryClient = createQueryClient();
    const overviewKey = benchmarkQueryKeys.overview();
    const overview = { included_cases: 1 };
    queryClient.setQueryData(overviewKey, overview);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValueOnce(new TypeError("offline")),
    );

    await expect(runParserBenchmarkCommand(queryClient, {})).rejects.toThrow(
      "offline",
    );
    expect(queryClient.getQueryData(overviewKey)).toBe(overview);
    expect(queryClient.getQueryState(overviewKey)?.isInvalidated).toBe(false);
  });
});
