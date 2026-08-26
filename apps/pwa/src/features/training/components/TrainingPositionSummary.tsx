import { Eye, Target } from "lucide-react";
import { Fragment } from "react";

import "./TrainingPositionSummary.css";
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
  TrainingPositionFilter,
  TrainingProgress,
} from "../../../shared/types/training";

type TrainingPositionProgress = Pick<
  TrainingProgress,
  | "position_summaries"
  | "unpositioned_hands"
  | "unpositioned_needs_review_hands"
>;

export interface TrainingPositionFocus {
  filter: TrainingPositionFilter;
  label: string;
  reason: string;
}

export interface TrainingPositionSummaryProps {
  controlsDisabled: boolean;
  focus: TrainingPositionFocus | null;
  onFilterChange: (filter: TrainingPositionFilter) => void | Promise<void>;
  onReview: (filter: TrainingPositionFilter) => void | Promise<void>;
  progress: TrainingPositionProgress;
  showFocus: boolean;
}

function positionFilter(position: string): TrainingPositionFilter {
  return {
    kind: "position",
    position,
    label: position,
  };
}

function unpositionedFilter(): TrainingPositionFilter {
  return {
    kind: "unpositioned",
    label: "Unpositioned",
  };
}

export function TrainingPositionSummary({
  controlsDisabled,
  focus,
  onFilterChange,
  onReview,
  progress,
  showFocus,
}: TrainingPositionSummaryProps) {
  const summaries = progress.position_summaries ?? [];
  const unpositionedHands = progress.unpositioned_hands ?? 0;
  const unpositionedNeedsReview = progress.unpositioned_needs_review_hands ?? 0;
  if (summaries.length === 0 && unpositionedHands <= 0) {
    return null;
  }

  return (
    <section
      className="training-progress-section"
      aria-labelledby="training-positions-title"
    >
      <SectionHeading
        className="training-section-heading"
        heading="By position"
        headingId="training-positions-title"
      >
        {(showFocus && focus) || unpositionedHands > 0 ? (
          <span className="training-position-heading-actions">
            {showFocus && focus ? (
              <ButtonControl
                variant="secondary"
                className="training-focus-action"
                onClick={() => void onReview(focus.filter)}
                disabled={controlsDisabled}
                title={focus.reason}
                aria-label={`Focus ${focus.filter.kind === "unpositioned" ? "unpositioned" : `${focus.label} position`} reviews: ${focus.reason}`}
              >
                <Target size={13} aria-hidden="true" />
                Focus {focus.label}
              </ButtonControl>
            ) : null}
            {unpositionedHands > 0 ? (
              <span className="training-section-context training-position-context">
                <ButtonControl
                  variant="ghost"
                  className="training-position-unrecorded"
                  onClick={() => void onFilterChange(unpositionedFilter())}
                  disabled={controlsDisabled}
                  aria-label={`Show ${unpositionedHands} unpositioned ${unpositionedHands === 1 ? "hand" : "hands"}`}
                  title="Show training hands"
                >
                  {unpositionedHands} unrecorded
                  <Eye size={11} aria-hidden="true" />
                </ButtonControl>
                {unpositionedNeedsReview > 0 ? (
                  <ButtonControl
                    variant="secondary"
                    className="training-certainty-review"
                    onClick={() => void onReview(unpositionedFilter())}
                    disabled={controlsDisabled}
                    aria-label={`Review unpositioned differences (${unpositionedNeedsReview})`}
                    title="Open pending reviews"
                  >
                    <Target size={11} aria-hidden="true" />
                    {unpositionedNeedsReview}
                  </ButtonControl>
                ) : null}
              </span>
            ) : null}
          </span>
        ) : null}
      </SectionHeading>
      {summaries.length > 0 ? (
        <table className="training-street-table training-position-table">
          <thead>
            <tr>
              <th>Position</th>
              <th>Hands</th>
              <th>Action</th>
              <th>Exact</th>
              <th>Avg EV loss</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {summaries.map((summary) => {
              const filter = positionFilter(summary.position);
              return (
                <Fragment key={summary.position}>
                  <tr className={summary.trend ? "has-trend" : undefined}>
                    <th scope="row">
                      <ButtonControl
                        variant="ghost"
                        className="training-summary-drilldown"
                        onClick={() => void onFilterChange(filter)}
                        disabled={controlsDisabled}
                        aria-label={[
                          `Show ${summary.reviewed_hands} ${summary.reviewed_hands === 1 ? "hand" : "hands"} recorded at ${summary.position}`,
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
                        <span>{summary.position}</span>
                        <Eye size={12} aria-hidden="true" />
                      </ButtonControl>
                    </th>
                    <td>{summary.reviewed_hands}</td>
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
                          onClick={() => void onReview(filter)}
                          disabled={controlsDisabled}
                          aria-label={`Review ${summary.position} position differences (${summary.needs_review_hands})`}
                          title="Open pending reviews"
                        >
                          <Target size={11} aria-hidden="true" />
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
                        <TrainingPerformanceTrend
                          trend={summary.trend}
                          hiddenFromAssistiveTechnology
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
