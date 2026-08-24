import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../shared/api/generated/openapi";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { getTrainingProgress, toTrainingProgress } from "./trainingApi";

type TrainingProgressResponse = components["schemas"]["TrainingProgress"];

const progressResponse = {} as TrainingProgressResponse;

afterEach(resetApiMocks);

describe("training API adapter", () => {
  it("preserves the generated response object and JSON shape", () => {
    expect(toTrainingProgress(progressResponse)).toBe(progressResponse);
  });

  it("keeps the default progress request backward compatible", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(progressResponse));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getTrainingProgress()).resolves.toEqual(progressResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/training/progress",
      { credentials: "include" },
    );
  });

  it("encodes review and lesson filters in their stable order", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(progressResponse));
    vi.stubGlobal("fetch", fetchMock);

    await getTrainingProgress(
      "ev_loss",
      "turn",
      null,
      "all",
      "river",
      "  check raise  ",
      "ev_loss",
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/training/progress?review_order=ev_loss&review_street=turn&lesson_order=ev_loss&lesson_street=river&lesson_query=check+raise",
      { credentials: "include" },
    );
  });
});
