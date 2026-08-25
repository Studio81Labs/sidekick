import { Eye, RefreshCcw } from "lucide-react";

import "./TrainingDecisionList.css";
import { cardToDisplay } from "../../../shared/lib/cardPresentation";
import { ButtonControl } from "../../../shared/components/FormControls";
import { formatEvLossBb } from "../../../shared/lib/metricPresentation";
import { StateMessage } from "../../../shared/components/StateMessage";
import type { RecommendationAction } from "../../../shared/types/recommendations";
import type {
  TrainingCertainty,
  TrainingOutcome,
  TrainingPositionFilter,
  TrainingRecentHand,
  TrainingSolverFilter,
  TrainingStreetFilter,
} from "../../../shared/types/training";

export type TrainingDecisionListView = "recent" | "review" | "lessons";

export interface TrainingDecisionListProps {
  certaintyLabel: (certainty: TrainingCertainty) => string;
  decisionLabel: (
    action: RecommendationAction,
    sizing: number | null,
  ) => string;
  hands: TrainingRecentHand[];
  lessonFiltersActive: boolean;
  onOpen: (jobId: string, continueReviewQueue: boolean) => void | Promise<void>;
  onReopen: (jobId: string) => void | Promise<void>;
  openDisabled: boolean;
  positionFilter: TrainingPositionFilter | null;
  reopenDisabled: boolean;
  solverFilter: TrainingSolverFilter | null;
  streetFilter: TrainingStreetFilter | null;
  view: TrainingDecisionListView;
}

function outcomeLabel(outcome: TrainingOutcome): string {
  if (outcome === "match") {
    return "Exact match";
  }
  if (outcome === "mixed") {
    return "Supported mix";
  }
  if (outcome === "same_action") {
    return "Same action";
  }
  if (outcome === "mixed_action") {
    return "Supported action";
  }
  return "Different action";
}

function emptyMessage({
  lessonFiltersActive,
  positionFilter,
  solverFilter,
  streetFilter,
  view,
}: Pick<
  TrainingDecisionListProps,
  | "lessonFiltersActive"
  | "positionFilter"
  | "solverFilter"
  | "streetFilter"
  | "view"
>): string {
  if (view === "lessons") {
    return lessonFiltersActive
      ? "No saved lesson notes match these filters."
      : "No saved lesson notes yet.";
  }
  if (view === "review") {
    return "No action or sizing differences need review.";
  }
  if (solverFilter) {
    if (solverFilter.kind === "route") {
      return "No training hands were handled by this engine.";
    }
    if (solverFilter.kind === "fallback") {
      return "No training hands use this fallback.";
    }
    return "No training hands are missing engine attribution.";
  }
  if (positionFilter) {
    return positionFilter.kind === "position"
      ? `No training hands were recorded at ${positionFilter.label}.`
      : "No training hands have a recorded position.";
  }
  if (streetFilter) {
    return `No training hands were played on ${streetFilter.label}.`;
  }
  return "No recent training decisions.";
}

export function TrainingDecisionList({
  certaintyLabel,
  decisionLabel,
  hands,
  lessonFiltersActive,
  onOpen,
  onReopen,
  openDisabled,
  positionFilter,
  reopenDisabled,
  solverFilter,
  streetFilter,
  view,
}: TrainingDecisionListProps) {
  if (hands.length === 0) {
    return (
      <StateMessage centered className="training-review-empty" size="small">
        {emptyMessage({
          lessonFiltersActive,
          positionFilter,
          solverFilter,
          streetFilter,
          view,
        })}
      </StateMessage>
    );
  }

  return (
    <div className="recent-training-list">
      {hands.map((hand) => (
        <div className="recent-training-row" key={hand.job_id}>
          <ButtonControl
            variant="ghost"
            className="recent-training-open"
            onClick={() => void onOpen(hand.job_id, view === "review")}
            disabled={openDisabled}
            aria-label={`Open ${hand.original_filename} training review`}
          >
            <span className="recent-training-hand">
              <strong>
                {hand.hero_cards.length > 0
                  ? hand.hero_cards.map(cardToDisplay).join(" ")
                  : "Unknown cards"}
              </strong>
              <small>
                {hand.street ?? "Unknown street"} · {hand.original_filename}
                {hand.decision_certainty
                  ? ` · ${certaintyLabel(hand.decision_certainty)} certainty`
                  : ""}
              </small>
            </span>
            <span className="recent-training-lines">
              <small>
                You: {decisionLabel(hand.decision_action, hand.decision_sizing)}
              </small>
              <small>
                Solver:{" "}
                {decisionLabel(
                  hand.recommended_action,
                  hand.recommended_sizing,
                )}
              </small>
              {typeof hand.ev_loss_bb === "number" ? (
                <small className="recent-training-ev">
                  EV loss: {formatEvLossBb(hand.ev_loss_bb)}
                </small>
              ) : null}
              {hand.review_note ? (
                <small className="recent-training-note">
                  Note: {hand.review_note}
                </small>
              ) : null}
            </span>
            <em className={hand.reviewed_at ? "reviewed" : hand.outcome}>
              {hand.reviewed_at ? "Reviewed" : outcomeLabel(hand.outcome)}
            </em>
            <Eye size={15} aria-hidden="true" />
          </ButtonControl>
          {view !== "lessons" &&
          hand.reviewed_at &&
          hand.outcome !== "match" &&
          hand.outcome !== "mixed" ? (
            <ButtonControl
              variant="ghost"
              iconOnly
              className="recent-training-reopen"
              onClick={() => void onReopen(hand.job_id)}
              disabled={reopenDisabled}
              aria-label={`Reopen ${hand.original_filename} training review`}
              title="Reopen review"
            >
              <RefreshCcw size={14} aria-hidden="true" />
            </ButtonControl>
          ) : null}
        </div>
      ))}
    </div>
  );
}
