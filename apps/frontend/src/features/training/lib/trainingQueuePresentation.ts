import type {
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
import { benchmarkFieldLabel } from "../../../shared/lib/metricPresentation";
import { trainingDecisionLabel } from "../../../domains/training/model/trainingDecision";
import type { TrainingProgressView } from "./trainingPresentationTypes";

export function sameTrainingPositionFilter(
  left: TrainingPositionFilter | null,
  right: TrainingPositionFilter | null,
): boolean {
  if (left?.kind !== right?.kind) {
    return false;
  }
  if (!left || !right || left.kind === "unpositioned") {
    return true;
  }
  return right.kind === "position" && left.position === right.position;
}

export function trainingReviewQueueStatus(
  progress: TrainingProgress | null,
  view: TrainingProgressView,
  loading: boolean,
  order: TrainingReviewOrder,
  street: TrainingReviewStreet,
  difference: TrainingReviewDifference | null,
  certainty: TrainingReviewCertaintyFilter,
  reviewPosition: TrainingPositionFilter | null,
  lessonStreet: TrainingReviewStreet,
  lessonQuery: string,
  lessonOrder: TrainingReviewOrder,
  solverFilter: TrainingSolverFilter | null,
  positionFilter: TrainingPositionFilter | null,
  streetFilter: TrainingStreetFilter | null,
  certaintyFilter: TrainingCertaintyFilter | null,
): string {
  if (view === "lessons") {
    if (loading) {
      return "Reading saved lessons...";
    }
    const lessonCount =
      progress?.lesson_count ?? progress?.lesson_hands?.length ?? 0;
    const lessonMatchingHands =
      progress?.lesson_matching_hands ?? progress?.lesson_hands?.length ?? 0;
    const visibleLessons = progress?.lesson_hands?.length ?? 0;
    const filtersActive = lessonStreet !== "all" || lessonQuery.length > 0;
    const orderLabel = lessonOrder === "ev_loss" ? "highest-loss" : "newest";
    if (filtersActive) {
      if (lessonMatchingHands > visibleLessons) {
        return `Showing ${visibleLessons} ${orderLabel} of ${lessonMatchingHands} matching lessons.`;
      }
      if (lessonMatchingHands > 0) {
        return `${lessonMatchingHands} lesson note${lessonMatchingHands === 1 ? "" : "s"} ${lessonMatchingHands === 1 ? "matches" : "match"} these filters.`;
      }
      return "No saved lesson notes match these filters.";
    }
    if (lessonCount > visibleLessons) {
      return `Showing ${visibleLessons} ${orderLabel} of ${lessonCount} saved lesson notes.`;
    }
    if (lessonCount > 0) {
      return `${lessonCount} saved lesson note${lessonCount === 1 ? "" : "s"}.`;
    }
    return "No saved lesson notes yet.";
  }
  if (view === "recent" && solverFilter) {
    if (loading) {
      if (solverFilter.kind === "route") {
        return "Finding engine hands...";
      }
      return solverFilter.kind === "fallback"
        ? "Finding fallback hands..."
        : "Finding unattributed hands...";
    }
    const matchingHands =
      progress?.recent_matching_hands ?? progress?.recent_hands.length ?? 0;
    const visibleHands = progress?.recent_hands.length ?? 0;
    const kindLabel =
      solverFilter.kind === "route"
        ? "engine"
        : solverFilter.kind === "fallback"
          ? "fallback"
          : "unattributed";
    if (matchingHands > visibleHands) {
      return `Showing ${visibleHands} newest of ${matchingHands} ${kindLabel} hands.`;
    }
    if (solverFilter.kind === "route") {
      return `${matchingHands} training hand${matchingHands === 1 ? "" : "s"} handled by ${solverFilter.label}.`;
    }
    if (solverFilter.kind === "unattributed") {
      return `${matchingHands} training hand${matchingHands === 1 ? " has" : "s have"} no engine attribution.`;
    }
    return `${matchingHands} training hand${matchingHands === 1 ? "" : "s"} used this fallback.`;
  }
  if (view === "recent" && positionFilter) {
    if (loading) {
      return positionFilter.kind === "position"
        ? `Finding ${positionFilter.label} hands...`
        : "Finding unpositioned hands...";
    }
    const matchingHands =
      progress?.recent_matching_hands ?? progress?.recent_hands.length ?? 0;
    const visibleHands = progress?.recent_hands.length ?? 0;
    if (matchingHands > visibleHands) {
      return `Showing ${visibleHands} newest of ${matchingHands} ${positionFilter.label} hands.`;
    }
    if (positionFilter.kind === "position") {
      return `${matchingHands} training hand${matchingHands === 1 ? "" : "s"} recorded at ${positionFilter.label}.`;
    }
    return `${matchingHands} training hand${matchingHands === 1 ? " has" : "s have"} no recorded position.`;
  }
  if (view === "recent" && streetFilter) {
    if (loading) {
      return `Finding ${streetFilter.label} hands...`;
    }
    const matchingHands =
      progress?.recent_matching_hands ?? progress?.recent_hands.length ?? 0;
    const visibleHands = progress?.recent_hands.length ?? 0;
    if (matchingHands > visibleHands) {
      return `Showing ${visibleHands} newest of ${matchingHands} ${streetFilter.label} hands.`;
    }
    return `${matchingHands} training hand${matchingHands === 1 ? "" : "s"} played on ${streetFilter.label}.`;
  }
  if (view === "recent" && certaintyFilter) {
    if (loading) {
      return certaintyFilter.certainty === "unrated"
        ? "Finding unrated hands..."
        : `Finding ${certaintyFilter.label.toLowerCase()}-certainty hands...`;
    }
    const matchingHands =
      progress?.recent_matching_hands ?? progress?.recent_hands.length ?? 0;
    const visibleHands = progress?.recent_hands.length ?? 0;
    if (matchingHands > visibleHands) {
      return `Showing ${visibleHands} newest of ${matchingHands} ${certaintyFilter.label} hands.`;
    }
    if (certaintyFilter.certainty === "unrated") {
      return `${matchingHands} training hand${matchingHands === 1 ? " has" : "s have"} no certainty rating.`;
    }
    return `${matchingHands} training hand${matchingHands === 1 ? "" : "s"} rated ${certaintyFilter.label.toLowerCase()} certainty.`;
  }
  if (view !== "review") {
    return "Automation-only hands are not scored.";
  }
  if (loading) {
    return "Updating review queue...";
  }
  if (!progress) {
    return "No pending review hands.";
  }

  const matchingHands =
    progress.review_queue_hands ?? progress.review_queue.length;
  const actionScope = difference
    ? `for ${trainingDecisionLabel(difference.decision_action, null)} to ${trainingDecisionLabel(difference.recommended_action, null)}`
    : null;
  const streetScope = street === "all" ? "across all streets" : `on ${street}`;
  const certaintyScope =
    certainty === "all"
      ? null
      : certainty === "unrated"
        ? "without a certainty rating"
        : `with ${certainty} certainty`;
  const positionScope =
    reviewPosition?.kind === "position"
      ? `at ${reviewPosition.label}`
      : reviewPosition?.kind === "unpositioned"
        ? "without a recorded position"
        : null;
  const scope = [actionScope, streetScope, certaintyScope, positionScope]
    .filter(Boolean)
    .join(" ");
  if (matchingHands > progress.review_queue.length) {
    const orderLabel = order === "ev_loss" ? "highest-loss" : "newest";
    return `Showing ${progress.review_queue.length} ${orderLabel} of ${matchingHands} review hands ${scope}.`;
  }
  if (matchingHands > 0) {
    return `${matchingHands} pending review hand${matchingHands === 1 ? "" : "s"} ${scope}.`;
  }
  return `No pending review hands ${scope}.`;
}
