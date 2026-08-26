import type { components } from "@poker-hero/openapi-client";
import { requestJson } from "../../../shared/api/transport";
import type { JobRecord } from "../../../shared/types/jobs";
import { toJobRecord } from "../../jobs/api/jobsApi";

type JobRecordResponse = components["schemas"]["JobRecord"];

export async function requestRecommendation(
  jobId: string,
  requestId: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  const response = await requestJson<JobRecordResponse>(
    `/api/jobs/${jobId}/recommend`,
    {
      method: "POST",
      headers: { "X-Recommendation-Request-ID": requestId },
      signal,
    },
  );
  return toJobRecord(response);
}
