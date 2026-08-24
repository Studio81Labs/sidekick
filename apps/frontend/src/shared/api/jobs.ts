export {
  approveState,
  deleteJob,
  getJob,
  getProcessingJobs,
  imageUrl,
  updateJobMetadata,
} from "../../domains/jobs/api/jobsApi";
export { requestRecommendation } from "../../domains/recommendations/api/recommendationsApi";

import type { JobRecord } from "../types/jobs";
import type { PipelineSelection } from "../types/pipeline";
import { apiUrl, readJson } from "./core";

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
