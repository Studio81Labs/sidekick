import type { components } from "../../../shared/api/generated/openapi";
import { requestJson } from "../../../shared/api/transport";
import type { JobHistory } from "../../../shared/types/jobs";

type JobHistoryResponse = components["schemas"]["JobHistory"];

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
