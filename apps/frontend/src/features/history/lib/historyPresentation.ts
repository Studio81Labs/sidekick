import type { Card } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";

export interface HistoryItem {
  id: string;
  job: JobRecord;
  savedAt: string;
}

export function historyCards(job: JobRecord): Card[] {
  const state = job.approved_state ?? job.parser_result?.state;
  return state?.hero_cards.slice(0, 2) ?? [];
}

export function historyAction(job: JobRecord): string {
  if (job.recommendation) {
    return job.recommendation.action;
  }
  return job.approved_state ? "approved" : job.status;
}

export function relativeTimeLabel(isoDate: string, now = Date.now()): string {
  const elapsedSeconds = Math.max(
    0,
    Math.round((now - new Date(isoDate).getTime()) / 1000),
  );
  if (elapsedSeconds < 60) {
    return "just now";
  }
  const elapsedMinutes = Math.round(elapsedSeconds / 60);
  if (elapsedMinutes < 60) {
    return `${elapsedMinutes} min ago`;
  }
  const elapsedHours = Math.round(elapsedMinutes / 60);
  if (elapsedHours < 24) {
    return `${elapsedHours} hr ago`;
  }
  const elapsedDays = Math.round(elapsedHours / 24);
  return `${elapsedDays} day${elapsedDays === 1 ? "" : "s"} ago`;
}
