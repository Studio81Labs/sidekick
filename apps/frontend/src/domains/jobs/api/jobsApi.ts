import type { components } from "../../../shared/api/generated/openapi";
import { apiUrl, readJson } from "../../../shared/api/core";
import { requestJson } from "../../../shared/api/transport";
import type { JobQueue, JobRecord } from "../../../shared/types/jobs";
import type { PipelineSelection } from "../../../shared/types/pipeline";
import type { CanonicalState } from "../../../shared/types/poker";

type JobQueueResponse = components["schemas"]["JobQueue"];
type JobRecordResponse = components["schemas"]["JobRecord"];
export type JobMetadataUpdate = Required<
  Pick<
    components["schemas"]["ScreenshotMetadataRequest"],
    "title" | "notes" | "tags"
  >
>;

export function toJobRecord(response: JobRecordResponse): JobRecord {
  return response as unknown as JobRecord;
}

export function toJobQueue(response: JobQueueResponse): JobQueue {
  return response as unknown as JobQueue;
}

export function imageUrl(jobId: string): string {
  return apiUrl(`/api/jobs/${jobId}/image`);
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
  const response = await requestJson<JobRecordResponse>("/api/jobs", {
    method: "POST",
    body: form,
    signal,
  });
  const job = toJobRecord(response);
  return job.upload_request_id
    ? job
    : { ...job, upload_request_id: uploadRequestId };
}

export async function getJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  const response = await requestJson<JobRecordResponse>(`/api/jobs/${jobId}`, {
    ...(signal ? { signal } : {}),
  });
  return toJobRecord(response);
}

export async function getProcessingJobs(
  offset = 0,
  signal?: AbortSignal,
): Promise<JobQueue> {
  const query = offset > 0 ? `?offset=${offset}` : "";
  const response = await requestJson<JobQueueResponse>(`/api/jobs${query}`, {
    ...(signal ? { signal } : {}),
  });
  return toJobQueue(response);
}

export async function updateJobMetadata(
  jobId: string,
  metadata: JobMetadataUpdate,
): Promise<JobRecord> {
  const response = await requestJson<JobRecordResponse>(
    `/api/jobs/${encodeURIComponent(jobId)}/metadata`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(metadata),
    },
  );
  return toJobRecord(response);
}

export async function approveState(
  jobId: string,
  state: CanonicalState,
  signal?: AbortSignal,
): Promise<JobRecord> {
  const approval = {
    ...state,
    user_approved: true,
  } satisfies components["schemas"]["CanonicalState"];
  const response = await requestJson<JobRecordResponse>(
    `/api/jobs/${jobId}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(approval),
      signal,
    },
  );
  return toJobRecord(response);
}

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
