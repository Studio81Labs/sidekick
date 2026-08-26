import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../shared/api/generated/openapi";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { requestRecommendation } from "./recommendationsApi";

afterEach(resetApiMocks);

describe("recommendation API adapter", () => {
  it("preserves the caller request ID and abort signal", async () => {
    const job = { id: "a".repeat(32) } as components["schemas"]["JobRecord"];
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(job));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      requestRecommendation(
        job.id ?? "",
        "recommendation-1",
        controller.signal,
      ),
    ).resolves.toEqual(job);

    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/jobs/${job.id}/recommend`,
      {
        method: "POST",
        headers: { "X-Recommendation-Request-ID": "recommendation-1" },
        signal: controller.signal,
        credentials: "include",
      },
    );
  });
});
