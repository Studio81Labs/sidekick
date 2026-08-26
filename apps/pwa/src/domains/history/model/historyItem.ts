import type { JobRecord } from "../../../shared/types/jobs";

export interface HistoryItem {
  id: string;
  job: JobRecord;
  savedAt: string;
}
