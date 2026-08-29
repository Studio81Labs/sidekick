import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { jsonResponse, resetApiMocks } from "../../../test/api";
import { canonicalState } from "../../../test/analyzerHarness";
import type { components } from "@poker-hero/openapi-client";
import {
  approveState,
  deleteJob,
  getJob,
  getProcessingJobs,
  type JobMetadataUpdate,
  toJobQueue,
  toJobRecord,
  updateJobMetadata,
  uploadScreenshot,
} from "./jobsApi";

afterEach(resetApiMocks);

const jobResponse = {
  approved_state: null,
  archived_at: null,
  benchmark_included: false,
  created_at: "2026-08-24T00:00:00Z",
  error: null,
  id: "job/123",
  image_filename: "table.png",
  input_context: "legacy_player",
  notes: null,
  original_filename: "table.png",
  parser_auto_approval_eligible: null,
  parser_layout_profile: "generic",
  parser_provider: "mock",
  parser_result: null,
  recommendation: null,
  recommendation_engine: null,
  recommendation_pending: false,
  recommendation_provider: "mock",
  recommendation_request_id: null,
  status: "created",
  tags: [],
  title: null,
  training_decision: null,
  training_review_note: null,
  training_reviewed_at: null,
  updated_at: "2026-08-24T00:00:00Z",
  upload_request_id: null,
} satisfies components["schemas"]["JobRecord"];

describe("jobs API adapter", () => {
  it("preserves the required full metadata replacement contract", () => {
    expectTypeOf<JobMetadataUpdate>().toEqualTypeOf<{
      title: string | null;
      notes: string | null;
      tags: string[];
    }>();
  });

  it("maps generated job and queue responses into stable domain values", () => {
    expect(toJobRecord(jobResponse)).toEqual(jobResponse);
    expect(
      toJobQueue({
        jobs: [jobResponse],
        snapshot_version: "queue-snapshot",
        total: 1,
      }),
    ).toEqual({
      jobs: [jobResponse],
      snapshot_version: "queue-snapshot",
      total: 1,
    });
  });

  it("reads a job through the shared transport", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(jobResponse));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getJob("job/123")).resolves.toEqual(jobResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs/job/123",
      { credentials: "include" },
    );
  });

  it("reads a processing page at the requested offset", async () => {
    const queue = {
      jobs: [jobResponse],
      snapshot_version: "queue-snapshot",
      total: 1,
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(queue));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProcessingJobs(100)).resolves.toEqual(queue);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs?offset=100",
      { credentials: "include" },
    );
  });

  it("uploads multipart pipeline selection and restores a missing request ID", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(jobResponse));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["screenshot"], "table.png", {
      type: "image/png",
    });
    const controller = new AbortController();

    await expect(
      uploadScreenshot(file, "upload-1", "secret-token", controller.signal, {
        parser_provider: "ocr_cv",
        parser_layout_profile: "fortuna_nations",
        recommendation_provider: "local_solver",
        recommendation_engine: "postflop_solver",
      }),
    ).resolves.toEqual({ ...jobResponse, upload_request_id: "upload-1" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs",
      expect.objectContaining({
        method: "POST",
        signal: controller.signal,
        credentials: "include",
      }),
    );
    const form = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(form.get("file")).toBe(file);
    expect(form.get("upload_request_id")).toBe("upload-1");
    expect(form.get("parser_provider")).toBe("ocr_cv");
    expect(form.get("parser_layout_profile")).toBe("fortuna_nations");
    expect(form.get("recommendation_provider")).toBe("local_solver");
    expect(form.get("recommendation_engine")).toBe("postflop_solver");
  });

  it("authorizes the upload with the administrative OCR test credential", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(jobResponse));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["screenshot"], "table.png", { type: "image/png" });

    await uploadScreenshot(file, "upload-1", "secret-token");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer secret-token",
    );
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("updates screenshot metadata through the shared transport", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(jobResponse));
    vi.stubGlobal("fetch", fetchMock);
    const metadata = {
      title: "Turn bluff",
      notes: "Review the sizing.",
      tags: ["turn", "bluff"],
    };

    await expect(updateJobMetadata("job/123", metadata)).resolves.toEqual(
      jobResponse,
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs/job%2F123/metadata",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(metadata),
        credentials: "include",
      },
    );
  });

  it("approves canonical state through the generated request contract", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(jobResponse));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const state = { ...canonicalState(), user_approved: false };

    await expect(
      approveState("job/123", state, controller.signal),
    ).resolves.toEqual(jobResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs/job/123/approve",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...state, user_approved: true }),
        signal: controller.signal,
        credentials: "include",
      },
    );
  });

  it("deletes a screenshot without reading a successful empty body", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(deleteJob("job/123")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs/job%2F123",
      { method: "DELETE", credentials: "include" },
    );
  });

  it("treats an already missing screenshot as deleted", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(deleteJob("job/123")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
