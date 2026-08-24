import type { JobRecord } from "../types/jobs";
import type { RecommendationAction } from "../types/recommendations";
import type {
  TrainingCertainty,
  TrainingReviewOrder,
  TrainingReviewStreet,
} from "../types/training";
import { apiUrl, readJson } from "./core";

export { getTrainingProgress } from "../../domains/training/api/trainingApi";

export async function recordTrainingDecision(
  jobId: string,
  action: RecommendationAction,
  sizing: number | null,
  certainty: TrainingCertainty | null,
): Promise<JobRecord> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/decision`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, sizing, certainty }),
    credentials: "include",
  });
  return readJson<JobRecord>(response);
}

export async function completeTrainingReview(
  jobId: string,
  note: string | null,
): Promise<JobRecord> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/training-review`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
    credentials: "include",
  });
  return readJson<JobRecord>(response);
}

export async function reopenTrainingReview(jobId: string): Promise<JobRecord> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/training-review`), {
    method: "DELETE",
    credentials: "include",
  });
  return readJson<JobRecord>(response);
}

export function trainingLessonsExportUrl(
  lessonStreet: TrainingReviewStreet = "all",
  lessonQuery = "",
  lessonOrder: TrainingReviewOrder = "recent",
): string {
  const search = new URLSearchParams();
  if (lessonOrder !== "recent") {
    search.set("lesson_order", lessonOrder);
  }
  if (lessonStreet !== "all") {
    search.set("lesson_street", lessonStreet);
  }
  if (lessonQuery.trim()) {
    search.set("lesson_query", lessonQuery.trim());
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  return apiUrl(`/api/training/lessons/export${query}`);
}
