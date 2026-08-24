import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { jsonResponse, resetApiMocks } from "../../../test/api";
import type { components } from "../../../shared/api/generated/openapi";
import {
  getJob,
  getProcessingJobs,
  type JobMetadataUpdate,
  toJobQueue,
  toJobRecord,
  updateJobMetadata,
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
});
