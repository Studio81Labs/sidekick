import type { components } from "../../../shared/api/generated/openapi";
import { apiUrl } from "../../../shared/api/core";
import { requestJson } from "../../../shared/api/transport";
import type { JobQueue, JobRecord } from "../../../shared/types/jobs";

type JobQueueResponse = components["schemas"]["JobQueue"];
type JobRecordResponse = components["schemas"]["JobRecord"];

export function toJobRecord(response: JobRecordResponse): JobRecord {
  return response as unknown as JobRecord;
}

export function toJobQueue(response: JobQueueResponse): JobQueue {
  return response as unknown as JobQueue;
}

export function imageUrl(jobId: string): string {
  return apiUrl(`/api/jobs/${jobId}/image`);
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
