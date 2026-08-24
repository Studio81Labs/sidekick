import type { JobHistory } from "../types/jobs";
import { apiUrl, readJson } from "./core";

export { getHistory } from "../../domains/history/api/historyApi";

const HISTORY_ARCHIVE_BATCH_SIZE = 100;

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
    const response = await fetch(apiUrl("/api/history"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_ids: jobIds.slice(offset, offset + HISTORY_ARCHIVE_BATCH_SIZE),
      }),
      credentials: "include",
    });
    history = await readJson<JobHistory>(response);
  }
  if (history === null) {
    throw new Error("History archive did not process any jobs");
  }
  return history;
}
