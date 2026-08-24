export {
  getJob,
  getProcessingJobs,
  imageUrl,
  updateJobMetadata,
} from "../../domains/jobs/api/jobsApi";

import type { JobRecord } from "../types/jobs";
import type { PipelineSelection } from "../types/pipeline";
import type { CanonicalState } from "../types/poker";
import { apiUrl, readJson } from "./core";

export async function deleteJob(jobId: string): Promise<void> {
  const response = await fetch(
    apiUrl(`/api/jobs/${encodeURIComponent(jobId)}`),
    {
      method: "DELETE",
      credentials: "include",
    },
  );
  if (!response.ok && response.status !== 404) {
    await readJson<never>(response);
  }
}

export async function uploadScreenshot(
  file: File,
  uploadRequestId: string,
  signal?: AbortSignal,
  pipeline?: PipelineSelection,
): Promise<JobRecord> {
  const form = new FormData();
  form.append("file", file);
  form.append("upload_request_id", uploadRequestId);
  if (pipeline) {
    form.append("parser_provider", pipeline.parser_provider);
    form.append("parser_layout_profile", pipeline.parser_layout_profile);
    form.append("recommendation_provider", pipeline.recommendation_provider);
    if (pipeline.recommendation_engine) {
      form.append("recommendation_engine", pipeline.recommendation_engine);
    }
  }
  const response = await fetch(apiUrl("/api/jobs"), {
    method: "POST",
    body: form,
    signal,
    credentials: "include",
  });
  const job = await readJson<JobRecord>(response);
  return job.upload_request_id
    ? job
    : { ...job, upload_request_id: uploadRequestId };
}

export async function approveState(
  jobId: string,
  state: CanonicalState,
  signal?: AbortSignal,
): Promise<JobRecord> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/approve`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...state, user_approved: true }),
    signal,
    credentials: "include",
  });
  return readJson<JobRecord>(response);
}

export async function requestRecommendation(
  jobId: string,
  requestId: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/recommend`), {
    method: "POST",
    headers: { "X-Recommendation-Request-ID": requestId },
    signal,
    credentials: "include",
  });
  return readJson<JobRecord>(response);
}
