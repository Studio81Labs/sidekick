import { Eye, Target } from "lucide-react";
import { Fragment } from "react";

import { ButtonControl } from "../../../shared/components/FormControls";
import {
  benchmarkPercent,
  formatEvLossBb,
} from "../../../shared/lib/metricPresentation";
import { SectionHeading } from "../../../shared/components/SectionHeading";
import { TrainingPerformanceTrend } from "./TrainingPerformanceTrend";
import type { Street } from "../../../shared/types/poker";
import type {
  TrainingStreetFilter,
  TrainingStreetSummary as TrainingStreetSummaryModel,
} from "../../../shared/types/training";

export interface TrainingStreetFocus {
  reason: string;
  street: Street;
}

export interface TrainingStreetSummaryProps {
  controlsDisabled: boolean;
  focus: TrainingStreetFocus | null;
  onFilterChange: (filter: TrainingStreetFilter) => void | Promise<void>;
  onReview: (street: Street) => void | Promise<void>;
  reviewCounts?: Partial<Record<Street, number>> | null;
  showFocus: boolean;
  summaries: TrainingStreetSummaryModel[];
}

function streetLabel(street: Street): string {
  return `${street.slice(0, 1).toUpperCase()}${street.slice(1)}`;
}

export function TrainingStreetSummary({
  controlsDisabled,
  focus,
  onFilterChange,
  onReview,
  reviewCounts,
  showFocus,
  summaries,
}: TrainingStreetSummaryProps) {
  return (
    <section
      className="training-progress-section"
      aria-labelledby="training-streets-title"
    >
      <SectionHeading
        className="training-section-heading"
        heading="By street"
        headingId="training-streets-title"
      >
        {showFocus && focus ? (
          <ButtonControl
            variant="secondary"
            className="training-focus-action"
            onClick={() => void onReview(focus.street)}
            disabled={controlsDisabled}
            title={focus.reason}
            aria-label={`Focus ${focus.street} reviews: ${focus.reason}`}
          >
            <Target size={13} aria-hidden="true" />
            Focus {focus.street}
          </ButtonControl>
        ) : null}
      </SectionHeading>
      <table className="training-street-table">
        <thead>
          <tr>
            <th>Street</th>
            <th>Hands</th>
            <th>Action</th>
            <th>Exact</th>
            <th>Avg EV loss</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>
          {summaries.map((summary) => {
            const pendingReviews = reviewCounts?.[summary.street] ?? 0;
            return (
              <Fragment key={summary.street}>
                <tr className={summary.trend ? "has-trend" : undefined}>
                  <th scope="row">
                    <ButtonControl
                      variant="ghost"
                      className="training-summary-drilldown"
                      onClick={() =>
                        void onFilterChange({
                          street: summary.street,
                          label: streetLabel(summary.street),
                        })
                      }
                      disabled={controlsDisabled}
                      aria-label={`Show ${summary.reviewed_hands} ${summary.reviewed_hands === 1 ? "hand" : "hands"} played on ${summary.street}`}
                      title="Show training hands"
                    >
                      <span>{summary.street}</span>
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
                    {pendingReviews > 0 ? (
                      <ButtonControl
                        variant="secondary"
                        className="training-certainty-review"
                        onClick={() => void onReview(summary.street)}
                        disabled={controlsDisabled}
                        aria-label={`Review ${summary.street} street differences (${pendingReviews})`}
                        title={`Review ${summary.street} differences`}
                      >
                        <Target size={12} aria-hidden="true" />
                        {pendingReviews}
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
        </tbody>
      </table>
    </section>
  );
}
