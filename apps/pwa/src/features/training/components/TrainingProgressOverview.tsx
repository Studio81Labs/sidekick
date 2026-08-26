import "./TrainingProgressOverview.css";
import {
  benchmarkPercent,
  formatAccuracyDelta,
  formatEvLossBb,
  formatEvLossDeltaBb,
  trainingTrendTone,
} from "../../../shared/lib/metricPresentation";
import { SectionHeading } from "../../../shared/components/SectionHeading";
import { SummaryMetric } from "../../../shared/components/SummaryMetric";
import type { TrainingProgress } from "../../../shared/types/training";

type TrainingOverviewProgress = Pick<
  TrainingProgress,
  | "action_accuracy"
  | "average_ev_loss_bb"
  | "ev_compared_hands"
  | "exact_accuracy"
  | "needs_review_hands"
  | "reviewed_hands"
  | "trend"
>;

export interface TrainingProgressOverviewProps {
  progress: TrainingOverviewProgress;
}

export function TrainingProgressOverview({
  progress,
}: TrainingProgressOverviewProps) {
  const averageEvLoss =
    progress.ev_compared_hands > 0 && progress.average_ev_loss_bb !== null
      ? progress.average_ev_loss_bb
      : null;
  const trend = progress.trend ?? null;
  const trendEv =
    trend &&
    trend.average_ev_loss_delta_bb !== null &&
    trend.recent_average_ev_loss_bb !== null
      ? {
          average: trend.recent_average_ev_loss_bb,
          delta: trend.average_ev_loss_delta_bb,
        }
      : null;

  return (
    <>
      <div
        className={`training-progress-summary${progress.ev_compared_hands > 0 ? " has-ev" : ""}`}
        aria-label="Training progress summary"
      >
        <SummaryMetric label="reviewed" value={progress.reviewed_hands} />
        <SummaryMetric
          label="action match"
          value={benchmarkPercent(progress.action_accuracy)}
        />
        <SummaryMetric
          label="exact line"
          value={benchmarkPercent(progress.exact_accuracy)}
        />
        {averageEvLoss !== null ? (
          <SummaryMetric
            label="avg EV loss"
            value={formatEvLossBb(averageEvLoss)}
          />
        ) : null}
        <SummaryMetric
          attention={progress.needs_review_hands > 0}
          label="needs review"
          value={progress.needs_review_hands}
        />
      </div>

      {trend ? (
        <section
          className="training-progress-section training-trend-section"
          aria-labelledby="training-trend-title"
        >
          <SectionHeading
            className="training-section-heading training-trend-heading"
            heading="Recent trend"
            headingId="training-trend-title"
          >
            <span>
              Last {trend.window_hands} vs previous {trend.window_hands}
            </span>
          </SectionHeading>
          <div
            className={`training-trend-grid${trend.average_ev_loss_delta_bb !== null ? " has-ev" : ""}`}
          >
            <div>
              <span>Action match</span>
              <strong>{benchmarkPercent(trend.recent_action_accuracy)}</strong>
              <em className={trainingTrendTone(trend.action_accuracy_delta)}>
                {formatAccuracyDelta(trend.action_accuracy_delta)}
              </em>
            </div>
            <div>
              <span>Exact line</span>
              <strong>{benchmarkPercent(trend.recent_exact_accuracy)}</strong>
              <em className={trainingTrendTone(trend.exact_accuracy_delta)}>
                {formatAccuracyDelta(trend.exact_accuracy_delta)}
              </em>
            </div>
            {trendEv ? (
              <div>
                <span>Avg EV loss</span>
                <strong>{formatEvLossBb(trendEv.average)}</strong>
                <em className={trainingTrendTone(trendEv.delta, true)}>
                  {formatEvLossDeltaBb(trendEv.delta)}
                </em>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
    </>
  );
}
