import { ArrowRight, Target } from "lucide-react";

import "./TrainingActionDifferences.css";
import { ButtonControl } from "../../../shared/components/FormControls";
import { formatEvLossBb } from "../../../shared/lib/metricPresentation";
import { SectionHeading } from "../../../shared/components/SectionHeading";
import { StateMessage } from "../../../shared/components/StateMessage";
import type { RecommendationAction } from "../../../shared/types/recommendations";
import type {
  TrainingActionDifference,
  TrainingReviewDifference,
} from "../../../shared/types/training";

export interface TrainingActionDifferenceFocus {
  difference: TrainingReviewDifference;
  label: string;
  reason: string;
}

export interface TrainingActionDifferencesProps {
  actionLabel: (action: RecommendationAction) => string;
  controlsDisabled: boolean;
  differences: TrainingActionDifference[] | null | undefined;
  focus: TrainingActionDifferenceFocus | null;
  onReview: (difference: TrainingReviewDifference) => void | Promise<void>;
  showFocus: boolean;
}

export function TrainingActionDifferences({
  actionLabel,
  controlsDisabled,
  differences,
  focus,
  onReview,
  showFocus,
}: TrainingActionDifferencesProps) {
  if (!differences || differences.length === 0) {
    return null;
  }

  return (
    <section
      className="training-progress-section training-differences-section"
      aria-labelledby="training-differences-title"
    >
      <SectionHeading
        className="training-section-heading training-differences-heading"
        heading="Common differences"
        headingId="training-differences-title"
      >
        <span className="training-differences-heading-actions">
          <span className="training-differences-context">
            Unsupported action choices
          </span>
          {showFocus && focus ? (
            <ButtonControl
              variant="secondary"
              className="training-focus-action"
              onClick={() => void onReview(focus.difference)}
              disabled={controlsDisabled}
              title={focus.reason}
              aria-label={`Focus ${focus.label} differences: ${focus.reason}`}
            >
              <Target size={13} aria-hidden="true" />
              Focus {focus.label}
            </ButtonControl>
          ) : null}
        </span>
      </SectionHeading>
      <div className="training-differences-list">
        {differences.slice(0, 3).map((difference) => {
          const decisionLabel = actionLabel(difference.decision_action);
          const recommendationLabel = actionLabel(
            difference.recommended_action,
          );
          return (
            <div
              key={`${difference.decision_action}-${difference.recommended_action}`}
              className="training-difference"
            >
              <div className="training-difference-actions">
                <strong>{decisionLabel}</strong>
                <ArrowRight size={13} aria-hidden="true" />
                <strong>{recommendationLabel}</strong>
              </div>
              <span>
                {difference.hands} {difference.hands === 1 ? "hand" : "hands"}
              </span>
              <em>
                {difference.ev_compared_hands > 0 &&
                difference.average_ev_loss_bb !== null
                  ? `${formatEvLossBb(difference.average_ev_loss_bb)} avg loss`
                  : "EV ungraded"}
              </em>
              {difference.needs_review_hands > 0 ? (
                <ButtonControl
                  variant="secondary"
                  className="training-difference-review"
                  onClick={() => void onReview(difference)}
                  disabled={controlsDisabled}
                  aria-label={`Review ${decisionLabel} to ${recommendationLabel} differences (${difference.needs_review_hands})`}
                  title={`${difference.needs_review_hands} pending review${difference.needs_review_hands === 1 ? "" : "s"}`}
                >
                  <Target size={12} aria-hidden="true" />
                  {difference.needs_review_hands}
                </ButtonControl>
              ) : (
                <StateMessage
                  as="span"
                  centered
                  className="training-difference-review-empty"
                  size="compact"
                  aria-label={`No pending ${decisionLabel} to ${recommendationLabel} reviews`}
                >
                  —
                </StateMessage>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
