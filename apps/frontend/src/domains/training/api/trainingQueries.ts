import { queryOptions, useQuery } from "@tanstack/react-query";

import type {
  TrainingCertaintyFilter,
  TrainingPositionFilter,
  TrainingReviewCertaintyFilter,
  TrainingReviewDifference,
  TrainingReviewOrder,
  TrainingReviewStreet,
  TrainingSolverFilter,
  TrainingStreetFilter,
} from "../../../shared/types/training";
import { getTrainingProgress } from "./trainingApi";

export interface TrainingProgressQuery {
  certaintyFilter?: TrainingCertaintyFilter | null;
  lessonOrder?: TrainingReviewOrder;
  lessonQuery?: string;
  lessonStreet?: TrainingReviewStreet;
  positionFilter?: TrainingPositionFilter | null;
  reviewCertainty?: TrainingReviewCertaintyFilter;
  reviewDifference?: TrainingReviewDifference | null;
  reviewOrder?: TrainingReviewOrder;
  reviewPositionFilter?: TrainingPositionFilter | null;
  reviewStreet?: TrainingReviewStreet;
  solverFilter?: TrainingSolverFilter | null;
  streetFilter?: TrainingStreetFilter | null;
}

export function normalizeTrainingProgressQuery(
  query: TrainingProgressQuery = {},
) {
  return {
    certaintyFilter: query.certaintyFilter ?? null,
    lessonOrder: query.lessonOrder ?? "recent",
    lessonQuery: query.lessonQuery?.trim() ?? "",
    lessonStreet: query.lessonStreet ?? "all",
    positionFilter: query.positionFilter ?? null,
    reviewCertainty: query.reviewCertainty ?? "all",
    reviewDifference: query.reviewDifference ?? null,
    reviewOrder: query.reviewOrder ?? "recent",
    reviewPositionFilter: query.reviewPositionFilter ?? null,
    reviewStreet: query.reviewStreet ?? "all",
    solverFilter: query.solverFilter ?? null,
    streetFilter: query.streetFilter ?? null,
  };
}

export const trainingQueryKeys = {
  all: ["training"] as const,
  progress: (query: TrainingProgressQuery = {}) =>
    [
      ...trainingQueryKeys.all,
      "progress",
      normalizeTrainingProgressQuery(query),
    ] as const,
};

export function trainingProgressQueryOptions(
  query: TrainingProgressQuery = {},
) {
  const normalized = normalizeTrainingProgressQuery(query);
  return queryOptions({
    queryKey: trainingQueryKeys.progress(normalized),
    queryFn: ({ signal }) =>
      getTrainingProgress(
        normalized.reviewOrder,
        normalized.reviewStreet,
        normalized.reviewDifference,
        normalized.reviewCertainty,
        normalized.lessonStreet,
        normalized.lessonQuery,
        normalized.lessonOrder,
        normalized.solverFilter,
        normalized.positionFilter,
        normalized.streetFilter,
        normalized.certaintyFilter,
        normalized.reviewPositionFilter,
        signal,
      ),
    staleTime: 0,
  });
}

export function useTrainingProgressQuery(
  query: TrainingProgressQuery = {},
  enabled = true,
) {
  return useQuery({
    ...trainingProgressQueryOptions(query),
    enabled,
  });
}
