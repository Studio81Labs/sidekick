import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "@poker-hero/openapi-client";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
  completeTrainingReview,
  getTrainingProgress,
  recordTrainingDecision,
  reopenTrainingReview,
  trainingLessonsExportUrl,
  toTrainingProgress,
} from "./trainingApi";

type TrainingProgressResponse = components["schemas"]["TrainingProgress"];

const progressResponse = {} as TrainingProgressResponse;

afterEach(resetApiMocks);

describe("training API adapter", () => {
  it("preserves the generated response object and JSON shape", () => {
    expect(toTrainingProgress(progressResponse)).toBe(progressResponse);
  });

  it("encodes lesson export filters in stable order", () => {
    expect(trainingLessonsExportUrl("turn", "check raise", "ev_loss")).toBe(
      "http://localhost:8000/api/training/lessons/export?lesson_order=ev_loss&lesson_street=turn&lesson_query=check+raise",
    );
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

  it("preserves training mutation signatures and generated JSON payloads", async () => {
    const jobId = "a".repeat(32);
    const jobResponse = { id: jobId } as components["schemas"]["JobRecord"];
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse(jobResponse)));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      recordTrainingDecision(jobId, "raise", 12.5, "high"),
    ).resolves.toEqual(jobResponse);
    await expect(
      completeTrainingReview(jobId, "Count combinations."),
    ).resolves.toEqual(jobResponse);
    await expect(reopenTrainingReview(jobId)).resolves.toEqual(jobResponse);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `http://localhost:8000/api/jobs/${jobId}/decision`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "raise",
          sizing: 12.5,
          certainty: "high",
        }),
        credentials: "include",
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `http://localhost:8000/api/jobs/${jobId}/training-review`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: "Count combinations." }),
        credentials: "include",
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `http://localhost:8000/api/jobs/${jobId}/training-review`,
      { method: "DELETE", credentials: "include" },
    );
  });
});
