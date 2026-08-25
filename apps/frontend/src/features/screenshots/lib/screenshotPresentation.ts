import type { JobRecord } from "../../../shared/types/jobs";

export function screenshotLabel(
  job: Pick<JobRecord, "original_filename" | "title">,
): string {
  return typeof job.title === "string" && job.title.trim()
    ? job.title.trim()
    : job.original_filename;
}
