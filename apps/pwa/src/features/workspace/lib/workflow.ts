import type { JobRecord } from "../../../shared/types/jobs";

export function isHistoryReady(job: JobRecord): boolean {
  return (
    job.archived_at === null &&
    job.status !== "error" &&
    (job.status === "approved" || job.approved_state !== null)
  );
}

export function isProcessingJobInProgress(job: JobRecord): boolean {
  return job.archived_at === null && job.status === "created";
}

export function createLocalErrorJob(
  file: File,
  message: string,
  index: number,
  uploadRequestId: string,
): JobRecord {
  const timestamp = new Date().toISOString();
  return {
    id: `local-error-${Date.now()}-${index}`,
    status: "error",
    upload_request_id: uploadRequestId,
    original_filename: file.name,
    image_filename: "",
    parser_provider: "client",
    parser_result: null,
    approved_state: null,
    benchmark_included: false,
    archived_at: null,
    error: message,
    created_at: timestamp,
    updated_at: timestamp,
  };
}
