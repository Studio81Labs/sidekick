import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { uploadScreenshotCommand } from "./uploadScreenshotCommand";

afterEach(resetApiMocks);

describe("upload screenshot command", () => {
  it("preserves upload identity, signal, pipeline, and explicit cache effects", async () => {
    const queryClient = createQueryClient();
    const created = jobRecord({
      id: "a".repeat(32),
      upload_request_id: null,
    });
    const processingKey = jobQueryKeys.processingPage(0);
    const historyKey = historyQueryKeys.page();
    queryClient.setQueryData(processingKey, { jobs: [], total: 0 });
    queryClient.setQueryData(historyKey, { jobs: [], total: 0 });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(created));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["screenshot"], "table.png");
    const controller = new AbortController();

    const outcome = await uploadScreenshotCommand(queryClient, {
      file,
      requestId: "upload-1",
      signal: controller.signal,
      pipeline: {
        parser_provider: "ocr_cv",
        parser_layout_profile: "fortuna_nations",
        recommendation_provider: "local_solver",
        recommendation_engine: "postflop_solver",
      },
    });

    const expectedJob = { ...created, upload_request_id: "upload-1" };
    expect(outcome).toEqual({
      job: expectedJob,
      cache: {
        updated: jobQueryKeys.detail(created.id),
        invalidated: [jobQueryKeys.processing()],
      },
    });
    expect(queryClient.getQueryData(jobQueryKeys.detail(created.id))).toEqual(
      expectedJob,
    );
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(historyKey)?.isInvalidated).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs",
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("leaves Query state untouched when one upload fails", async () => {
    const queryClient = createQueryClient();
    const processingKey = jobQueryKeys.processingPage(0);
    const processing = { jobs: [], total: 0 };
    queryClient.setQueryData(processingKey, processing);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValueOnce(new TypeError("offline")),
    );

    await expect(
      uploadScreenshotCommand(queryClient, {
        file: new File(["screenshot"], "table.png"),
        requestId: "upload-2",
      }),
    ).rejects.toThrow("offline");

    expect(queryClient.getQueryData(processingKey)).toBe(processing);
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(false);
  });
});
