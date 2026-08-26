import type { components } from "@poker-hero/openapi-client";
import { requestJson } from "../../../shared/api/transport";
import type { JobHistory } from "../../../shared/types/jobs";

type JobHistoryResponse = components["schemas"]["JobHistory"];
type ArchiveJobsRequest = components["schemas"]["ArchiveJobsRequest"];

const HISTORY_ARCHIVE_BATCH_SIZE = 100;

export function toJobHistory(response: JobHistoryResponse): JobHistory {
  return response as unknown as JobHistory;
}

export async function getHistory(
  offset = 0,
  query = "",
  limit?: number,
  signal?: AbortSignal,
): Promise<JobHistory> {
  const params = new URLSearchParams();
  if (offset > 0) {
    params.set("offset", String(offset));
  }
  if (query.trim()) {
    params.set("query", query.trim());
  }
  if (limit !== undefined) {
    params.set("limit", String(limit));
  }
  const queryString = params.size > 0 ? `?${params.toString()}` : "";
  const response = await requestJson<JobHistoryResponse>(
    `/api/history${queryString}`,
    signal ? { signal } : undefined,
  );
  return toJobHistory(response);
}

export async function archiveJobs(jobIds: string[]): Promise<JobHistory> {
  if (jobIds.length === 0) {
    throw new Error("At least one job is required to archive history");
  }

  let history: JobHistory | null = null;
  for (
    let offset = 0;
    offset < jobIds.length;
    offset += HISTORY_ARCHIVE_BATCH_SIZE
  ) {
    const request = {
      job_ids: jobIds.slice(offset, offset + HISTORY_ARCHIVE_BATCH_SIZE),
    } satisfies ArchiveJobsRequest;
    const response = await requestJson<JobHistoryResponse>("/api/history", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    history = toJobHistory(response);
  }
  if (history === null) {
    throw new Error("History archive did not process any jobs");
  }
  return history;
}
