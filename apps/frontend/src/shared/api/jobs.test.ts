import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, resetApiMocks } from "../../test/api";
import {
  deleteJob,
  getProcessingJobs,
  requestRecommendation,
  updateJobMetadata,
  uploadScreenshot,
} from "./jobs";
import {
  getJob as getDomainJob,
  updateJobMetadata as updateDomainJobMetadata,
} from "../../domains/jobs/api/jobsApi";
import { getJob as getCompatibilityJob } from "./jobs";

afterEach(resetApiMocks);

it("preserves the shared job-read compatibility export identity", () => {
  expect(getCompatibilityJob).toBe(getDomainJob);
  expect(updateJobMetadata).toBe(updateDomainJobMetadata);
});

describe("screenshot management", () => {
  it("updates title, notes and tags on a screenshot", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "job/123" }));
    vi.stubGlobal("fetch", fetchMock);
    const metadata = {
      title: "Turn bluff",
      notes: "Review the sizing.",
      tags: ["turn", "bluff"],
    };

    await updateJobMetadata("job/123", metadata);

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

  it("permanently deletes a screenshot without reading a 204 body", async () => {
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
});

describe("getProcessingJobs", () => {
  it("requests the next processing page from the current loaded offset", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        total: 125,
        jobs: [],
        snapshot_version: "queue-snapshot",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getProcessingJobs(100);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs?offset=100",
      { credentials: "include" },
    );
  });
});

describe("uploadScreenshot", () => {
  it("sends and retains the client request identity", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        id: "job-123",
        status: "parsed",
        original_filename: "table.png",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["image"], "table.png", { type: "image/png" });

    const job = await uploadScreenshot(file, "upload-request-123");

    const request = fetchMock.mock.calls[0][1];
    expect(request.body).toBeInstanceOf(FormData);
    expect((request.body as FormData).get("file")).toBe(file);
    expect((request.body as FormData).get("upload_request_id")).toBe(
      "upload-request-123",
    );
    expect(job.upload_request_id).toBe("upload-request-123");
  });

  it("sends a selected analysis pipeline with the screenshot", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        id: "job-123",
        status: "parsed",
        original_filename: "table.png",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["image"], "table.png", { type: "image/png" });

    await uploadScreenshot(file, "upload-request-123", undefined, {
      parser_provider: "ocr_cv",
      parser_layout_profile: "fortuna_nations",
      recommendation_provider: "local_solver",
      recommendation_engine: "postflop_solver",
    });

    const form = fetchMock.mock.calls[0][1].body as FormData;
    expect(form.get("parser_provider")).toBe("ocr_cv");
    expect(form.get("parser_layout_profile")).toBe("fortuna_nations");
    expect(form.get("recommendation_provider")).toBe("local_solver");
    expect(form.get("recommendation_engine")).toBe("postflop_solver");
  });
});

describe("requestRecommendation", () => {
  it("sends the client recommendation identity", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        id: "job-123",
        status: "recommended",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await requestRecommendation("job-123", "recommendation-request-123");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/jobs/job-123/recommend",
      {
        method: "POST",
        headers: {
          "X-Recommendation-Request-ID": "recommendation-request-123",
        },
        signal: undefined,
        credentials: "include",
      },
    );
  });
});
