import type { components } from "../../../shared/api/generated/openapi";
import { requestJson } from "../../../shared/api/transport";
import type { JobRecord } from "../../../shared/types/jobs";
import type { RecommendationAction } from "../../../shared/types/recommendations";
import type {
  TrainingCertainty,
  TrainingCertaintyFilter,
  TrainingPositionFilter,
  TrainingProgress,
  TrainingReviewCertaintyFilter,
  TrainingReviewDifference,
  TrainingReviewOrder,
  TrainingReviewStreet,
  TrainingSolverFilter,
  TrainingStreetFilter,
} from "../../../shared/types/training";
import { toJobRecord } from "../../jobs/api/jobsApi";

type TrainingProgressResponse = components["schemas"]["TrainingProgress"];
type JobRecordResponse = components["schemas"]["JobRecord"];
export type TrainingDecisionUpdate = Required<
  Pick<
    components["schemas"]["TrainingDecisionRequest"],
    "action" | "sizing" | "certainty"
  >
>;
export type TrainingReviewUpdate = Required<
  Pick<components["schemas"]["TrainingReviewRequest"], "note">
>;

export function toTrainingProgress(
  response: TrainingProgressResponse,
): TrainingProgress {
  return response as unknown as TrainingProgress;
}

export async function getTrainingProgress(
  reviewOrder: TrainingReviewOrder = "recent",
  reviewStreet: TrainingReviewStreet = "all",
  reviewDifference: TrainingReviewDifference | null = null,
  reviewCertainty: TrainingReviewCertaintyFilter = "all",
  lessonStreet: TrainingReviewStreet = "all",
  lessonQuery = "",
  lessonOrder: TrainingReviewOrder = "recent",
  solverFilter: TrainingSolverFilter | null = null,
  positionFilter: TrainingPositionFilter | null = null,
  streetFilter: TrainingStreetFilter | null = null,
  certaintyFilter: TrainingCertaintyFilter | null = null,
  reviewPositionFilter: TrainingPositionFilter | null = null,
  signal?: AbortSignal,
): Promise<TrainingProgress> {
  const search = new URLSearchParams();
  if (reviewOrder !== "recent") {
    search.set("review_order", reviewOrder);
  }
  if (reviewStreet !== "all") {
    search.set("review_street", reviewStreet);
  }
  if (reviewCertainty !== "all") {
    search.set("review_certainty", reviewCertainty);
  }
  if (reviewDifference) {
    search.set("review_decision_action", reviewDifference.decision_action);
    search.set(
      "review_recommended_action",
      reviewDifference.recommended_action,
    );
  }
  if (reviewPositionFilter?.kind === "position") {
    search.set("review_position", reviewPositionFilter.position);
  } else if (reviewPositionFilter?.kind === "unpositioned") {
    search.set("review_unpositioned", "true");
  }
  if (lessonOrder !== "recent") {
    search.set("lesson_order", lessonOrder);
  }
  if (lessonStreet !== "all") {
    search.set("lesson_street", lessonStreet);
  }
  if (lessonQuery.trim()) {
    search.set("lesson_query", lessonQuery.trim());
  }
  if (solverFilter?.kind === "fallback") {
    search.set("solver_fallback_key", solverFilter.key);
  } else if (solverFilter?.kind === "route") {
    search.set("solver_route_key", solverFilter.key);
  } else if (solverFilter?.kind === "unattributed") {
    search.set("solver_unattributed", "true");
  }
  if (positionFilter?.kind === "position") {
    search.set("recent_position", positionFilter.position);
  } else if (positionFilter?.kind === "unpositioned") {
    search.set("recent_unpositioned", "true");
  }
  if (streetFilter) {
    search.set("recent_street", streetFilter.street);
  }
  if (certaintyFilter) {
    search.set("recent_certainty", certaintyFilter.certainty);
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await requestJson<TrainingProgressResponse>(
    `/api/training/progress${query}`,
    signal ? { signal } : undefined,
  );
  return toTrainingProgress(response);
}

export async function recordTrainingDecision(
  jobId: string,
  action: RecommendationAction,
  sizing: number | null,
  certainty: TrainingCertainty | null,
): Promise<JobRecord> {
  const update: TrainingDecisionUpdate = { action, sizing, certainty };
  const response = await requestJson<JobRecordResponse>(
    `/api/jobs/${jobId}/decision`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    },
  );
  return toJobRecord(response);
}

export async function completeTrainingReview(
  jobId: string,
  note: string | null,
): Promise<JobRecord> {
  const update: TrainingReviewUpdate = { note };
  const response = await requestJson<JobRecordResponse>(
    `/api/jobs/${jobId}/training-review`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    },
  );
  return toJobRecord(response);
}

export async function reopenTrainingReview(jobId: string): Promise<JobRecord> {
  const response = await requestJson<JobRecordResponse>(
    `/api/jobs/${jobId}/training-review`,
    { method: "DELETE" },
  );
  return toJobRecord(response);
}
