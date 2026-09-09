import type { components } from "@poker-hero/openapi-client";
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

export async function uploadScreenshot(
  file: File,
  uploadRequestId: string,
  administratorToken: string,
  signal?: AbortSignal,
  pipeline?: PipelineSelection,
): Promise<JobRecord> {
  const form = new FormData();
  form.append("file", file);
  form.append("upload_request_id", uploadRequestId);
  if (pipeline) {
    form.append("parser_provider", pipeline.parser_provider);
    form.append("parser_layout_profile", pipeline.parser_layout_profile);
  }
  const response = await requestJson<JobRecordResponse>("/api/admin/ocr/jobs", {
    method: "POST",
    body: form,
    headers: { Authorization: `Bearer ${administratorToken}` },
    signal,
  });
  const job = toJobRecord(response);
  return job.upload_request_id
    ? job
    : { ...job, upload_request_id: uploadRequestId };
}

export async function getJob(
  jobId: string,
  administratorToken: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  const response = await requestJson<JobRecordResponse>(
    `/api/admin/ocr/jobs/${encodeURIComponent(jobId)}`,
    {
      headers: { Authorization: `Bearer ${administratorToken}` },
      ...(signal ? { signal } : {}),
    },
  );
  return toJobRecord(response);
}

export async function getProcessingJobs(
  offset = 0,
  administratorToken: string,
  signal?: AbortSignal,
): Promise<JobQueue> {
  const query = offset > 0 ? `?offset=${offset}` : "";
  const response = await requestJson<JobQueueResponse>(
    `/api/admin/ocr/jobs${query}`,
    {
      headers: { Authorization: `Bearer ${administratorToken}` },
      ...(signal ? { signal } : {}),
    },
  );
  return toJobQueue(response);
}

export async function updateJobMetadata(
  jobId: string,
  metadata: JobMetadataUpdate,
  administratorToken: string,
): Promise<JobRecord> {
  const response = await requestJson<JobRecordResponse>(
    `/api/admin/ocr/jobs/${encodeURIComponent(jobId)}/metadata`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${administratorToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(metadata),
    },
  );
  return toJobRecord(response);
}

export async function approveState(
  jobId: string,
  state: CanonicalState,
  administratorToken: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  const approval = {
    ...state,
    user_approved: true,
  } satisfies components["schemas"]["CanonicalState"];
  const response = await requestJson<JobRecordResponse>(
    `/api/admin/ocr/jobs/${encodeURIComponent(jobId)}/approve`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${administratorToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(approval),
      signal,
    },
  );
  return toJobRecord(response);
}

export async function deleteJob(
  jobId: string,
  administratorToken: string,
): Promise<void> {
  const response = await fetch(
    apiUrl(`/api/admin/ocr/jobs/${encodeURIComponent(jobId)}`),
    {
      method: "DELETE",
      credentials: "include",
      headers: { Authorization: `Bearer ${administratorToken}` },
    },
  );
  if (!response.ok && response.status !== 404) {
    await readJson<never>(response);
  }
}

export async function getJobImage(
  jobId: string,
  administratorToken: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await fetch(
    apiUrl(`/api/admin/ocr/jobs/${encodeURIComponent(jobId)}/image`),
    {
      credentials: "include",
      headers: { Authorization: `Bearer ${administratorToken}` },
      ...(signal ? { signal } : {}),
    },
  );
  if (!response.ok) {
    await readJson<never>(response);
  }
  return response.blob();
}
