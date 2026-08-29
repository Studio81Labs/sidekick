import type { JobRecord } from "../types/jobs";

export function isAdministrativeTestJob(
  job: Pick<JobRecord, "input_context">,
): boolean {
  return job.input_context === "administrative_test";
}
