import type {
  TrainingReviewOrder,
  TrainingReviewStreet,
} from "../types/training";
import { apiUrl } from "./core";

export {
  completeTrainingReview,
  getTrainingProgress,
  recordTrainingDecision,
  reopenTrainingReview,
} from "../../domains/training/api/trainingApi";

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
