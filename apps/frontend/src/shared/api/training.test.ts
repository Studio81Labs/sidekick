import { afterEach, describe, expect, it, vi } from "vitest";

import { getTrainingProgress as getDomainTrainingProgress } from "../../domains/training/api/trainingApi";
import { jsonResponse, resetApiMocks } from "../../test/api";
import { getTrainingProgress, trainingLessonsExportUrl } from "./training";

afterEach(resetApiMocks);

describe("training API", () => {
  it("preserves the domain progress adapter export identity", () => {
    expect(getTrainingProgress).toBe(getDomainTrainingProgress);
  });

  it("keeps the default progress request backward compatible", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await getTrainingProgress();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/training/progress",
      { credentials: "include" },
    );
  });

  it("encodes lesson export filters", () => {
    expect(trainingLessonsExportUrl("turn", "check raise", "ev_loss")).toBe(
      "http://localhost:8000/api/training/lessons/export?lesson_order=ev_loss&lesson_street=turn&lesson_query=check+raise",
    );
  });
});
