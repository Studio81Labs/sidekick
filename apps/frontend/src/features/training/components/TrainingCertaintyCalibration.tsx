import { Eye, Target } from "lucide-react";
import { Fragment } from "react";

import "./TrainingCertaintyCalibration.css";
import { ButtonControl } from "../../../shared/components/FormControls";
import {
  benchmarkPercent,
  formatEvLossBb,
} from "../../../shared/lib/metricPresentation";
import { SectionHeading } from "../../../shared/components/SectionHeading";
import {
  TrainingPerformanceTrend,
  trainingPerformanceTrendAccessibleLabel,
} from "./TrainingPerformanceTrend";
import type {
  TrainingCertainty,
  TrainingCertaintyFilter,
  TrainingProgress,
  TrainingReviewCertainty,
} from "../../../shared/types/training";

type TrainingCertaintyProgress = Pick<
  TrainingProgress,
  "certainty_summaries" | "unrated_hands" | "unrated_needs_review_hands"
>;

export interface TrainingCertaintyFocus {
  certainty: TrainingReviewCertainty;
  label: string;
  reason: string;
}

export interface TrainingCertaintyCalibrationProps {
  certaintyLabel: (certainty: TrainingCertainty) => string;
  controlsDisabled: boolean;
  focus: TrainingCertaintyFocus | null;
  onFilterChange: (filter: TrainingCertaintyFilter) => void | Promise<void>;
  onReview: (certainty: TrainingReviewCertainty) => void | Promise<void>;
  progress: TrainingCertaintyProgress;
  showFocus: boolean;
}

export function TrainingCertaintyCalibration({
  certaintyLabel,
  controlsDisabled,
  focus,
  onFilterChange,
  onReview,
  progress,
  showFocus,
}: TrainingCertaintyCalibrationProps) {
  const summaries = progress.certainty_summaries ?? [];
  const unratedHands = progress.unrated_hands ?? 0;
  const unratedNeedsReview = progress.unrated_needs_review_hands ?? 0;
  if (summaries.length === 0 && unratedHands <= 0) {
    return null;
  }

  return (
    <section
      className="training-progress-section training-certainty-section"
      aria-labelledby="training-certainty-title"
    >
      <SectionHeading
        className="training-section-heading"
        heading="Confidence calibration"
        headingId="training-certainty-title"
      >
        {showFocus && focus ? (
          <ButtonControl
            variant="secondary"
            className="training-focus-action"
            onClick={() => void onReview(focus.certainty)}
            disabled={controlsDisabled}
            title={focus.reason}
            aria-label={`Focus ${focus.certainty === "unrated" ? "unrated" : `${focus.certainty} certainty`} reviews: ${focus.reason}`}
          >
            <Target size={13} aria-hidden="true" />
            Focus {focus.label}
          </ButtonControl>
        ) : (
          <span className="training-section-context">
            Self-rated before reveal
          </span>
        )}
      </SectionHeading>
      <table className="training-street-table training-certainty-table">
        <thead>
          <tr>
            <th>Certainty</th>
            <th>Hands</th>
            <th>Action</th>
            <th>Exact</th>
            <th>Avg EV loss</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>
          {summaries.map((summary) => {
            const label = certaintyLabel(summary.certainty);
            return (
              <Fragment key={summary.certainty}>
                <tr className={summary.trend ? "has-trend" : undefined}>
                  <th scope="row">
                    <ButtonControl
                      variant="ghost"
                      className="training-summary-drilldown"
                      onClick={() =>
                        void onFilterChange({
                          certainty: summary.certainty,
                          label,
                        })
                      }
                      disabled={controlsDisabled}
                      aria-label={[
                        `Show ${summary.hands} ${summary.hands === 1 ? "hand" : "hands"} rated ${summary.certainty} certainty`,
                        summary.trend
                          ? trainingPerformanceTrendAccessibleLabel(
                              summary.trend,
                            )
                          : null,
                      ]
                        .filter(Boolean)
                        .join(". ")}
                      title="Show training hands"
                    >
                      <span>{label}</span>
                      <Eye size={12} aria-hidden="true" />
                    </ButtonControl>
                  </th>
                  <td>{summary.hands}</td>
                  <td>{benchmarkPercent(summary.action_accuracy)}</td>
                  <td>{benchmarkPercent(summary.exact_accuracy)}</td>
                  <td>
                    {summary.ev_compared_hands > 0 &&
                    summary.average_ev_loss_bb !== null
                      ? formatEvLossBb(summary.average_ev_loss_bb)
                      : "—"}
                  </td>
                  <td>
                    {(summary.needs_review_hands ?? 0) > 0 ? (
                      <ButtonControl
                        variant="secondary"
                        className="training-certainty-review"
                        onClick={() => void onReview(summary.certainty)}
                        disabled={controlsDisabled}
                        aria-label={`Review ${summary.certainty} certainty differences (${summary.needs_review_hands})`}
                        title={`Review ${summary.certainty}-certainty differences`}
                      >
                        <Target size={12} aria-hidden="true" />
                        {summary.needs_review_hands}
                      </ButtonControl>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
                {summary.trend ? (
                  <tr className="training-summary-trend-row">
                    <td colSpan={6}>
                      <TrainingPerformanceTrend trend={summary.trend} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
          {unratedHands > 0 ? (
            <tr className="training-unrated-row">
              <th scope="row">
                <ButtonControl
                  variant="ghost"
                  className="training-summary-drilldown"
                  onClick={() =>
                    void onFilterChange({
                      certainty: "unrated",
                      label: "Unrated",
                    })
                  }
                  disabled={controlsDisabled}
                  aria-label={`Show ${unratedHands} unrated ${unratedHands === 1 ? "hand" : "hands"}`}
                  title="Show training hands"
                >
                  <span>Unrated</span>
                  <Eye size={12} aria-hidden="true" />
                </ButtonControl>
              </th>
              <td>{unratedHands}</td>
              <td>—</td>
              <td>—</td>
              <td>—</td>
              <td>
                {unratedNeedsReview > 0 ? (
                  <ButtonControl
                    variant="secondary"
                    className="training-certainty-review"
                    onClick={() => void onReview("unrated")}
                    disabled={controlsDisabled}
                    aria-label={`Review unrated differences (${unratedNeedsReview})`}
                    title="Review unrated differences"
                  >
                    <Target size={12} aria-hidden="true" />
                    {unratedNeedsReview}
                  </ButtonControl>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
