import { describe, expect, it } from "vitest";

import {
  approvedJob,
  canonicalState,
  jobRecord,
} from "../../../test/analyzerHarness";
import {
  createLocalErrorJob,
  isHistoryReady,
  isProcessingJobInProgress,
} from "./workflow";

describe("workspace workflow", () => {
  it("treats only unarchived approved ground truth as history ready", () => {
    expect(isHistoryReady(approvedJob())).toBe(true);
    expect(
      isHistoryReady(
        jobRecord({ status: "parsed", approved_state: canonicalState() }),
      ),
    ).toBe(true);
    expect(isHistoryReady(jobRecord({ status: "parsed" }))).toBe(false);
    expect(isHistoryReady(jobRecord({ status: "created" }))).toBe(false);
    expect(
      isHistoryReady(jobRecord({ status: "error", error: "parse failed" })),
    ).toBe(false);
    expect(
      isHistoryReady({ ...approvedJob(), archived_at: "2026-07-10T00:02:00Z" }),
    ).toBe(false);
  });

  it("treats only unarchived created jobs as still processing", () => {
    expect(isProcessingJobInProgress(jobRecord({ status: "created" }))).toBe(
      true,
    );
    expect(isProcessingJobInProgress(jobRecord({ status: "parsed" }))).toBe(
      false,
    );
    expect(isProcessingJobInProgress(approvedJob())).toBe(false);
    expect(
      isProcessingJobInProgress(
        jobRecord({ status: "error", error: "parse failed" }),
      ),
    ).toBe(false);
    expect(
      isProcessingJobInProgress(
        jobRecord({ status: "created", archived_at: "2026-07-10T00:02:00Z" }),
      ),
    ).toBe(false);
  });

  it("builds a local failure placeholder that carries only the upload identity", () => {
    const file = new File(["bytes"], "table.png", { type: "image/png" });
    const localJob = createLocalErrorJob(file, "Upload failed", 2, "upload-1");

    expect(localJob).toMatchObject({
      status: "error",
      error: "Upload failed",
      original_filename: "table.png",
      image_filename: "",
      parser_provider: "client",
      parser_result: null,
      approved_state: null,
      benchmark_included: false,
      archived_at: null,
      upload_request_id: "upload-1",
    });
    expect(localJob.id).toMatch(/^local-error-\d+-2$/);
    expect(Object.keys(localJob).sort()).toEqual(
      [
        "approved_state",
        "archived_at",
        "benchmark_included",
        "created_at",
        "error",
        "id",
        "image_filename",
        "original_filename",
        "parser_provider",
        "parser_result",
        "status",
        "updated_at",
        "upload_request_id",
      ].sort(),
    );
  });
});
