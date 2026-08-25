import "./TrainingPerformanceTrend.css";
import {
  accessiblePointDelta,
  formatAccuracyDelta,
  formatEvLossDeltaBb,
  trainingTrendTone,
  trainingTrendWindowLabel,
} from "../../../shared/lib/metricPresentation";
import type { TrainingTrend } from "../../../shared/types/training";

export interface TrainingPerformanceTrendProps {
  hiddenFromAssistiveTechnology?: boolean;
  trend: TrainingTrend;
}

export function trainingPerformanceTrendAccessibleLabel(
  trend: TrainingTrend,
): string {
  const changes = [
    `action accuracy change ${accessiblePointDelta(trend.action_accuracy_delta)}`,
    `exact-line accuracy change ${accessiblePointDelta(trend.exact_accuracy_delta)}`,
  ];
  if (trend.average_ev_loss_delta_bb !== null) {
    changes.push(
      `average EV loss change ${formatEvLossDeltaBb(trend.average_ev_loss_delta_bb)}`,
    );
  }
  return `${trainingTrendWindowLabel(trend)}: ${changes.join(", ")}`;
}

export function TrainingPerformanceTrend({
  hiddenFromAssistiveTechnology = false,
  trend,
}: TrainingPerformanceTrendProps) {
  const title = trainingTrendWindowLabel(trend);
  return (
    <small
      className="training-summary-trend"
      aria-hidden={hiddenFromAssistiveTechnology || undefined}
      aria-label={
        hiddenFromAssistiveTechnology
          ? undefined
          : trainingPerformanceTrendAccessibleLabel(trend)
      }
    >
      <span>{title}</span>
      <strong>
        Action
        <em className={trainingTrendTone(trend.action_accuracy_delta)}>
          {formatAccuracyDelta(trend.action_accuracy_delta)}
        </em>
      </strong>
      <strong>
        Exact
        <em className={trainingTrendTone(trend.exact_accuracy_delta)}>
          {formatAccuracyDelta(trend.exact_accuracy_delta)}
        </em>
      </strong>
      {trend.average_ev_loss_delta_bb !== null ? (
        <strong>
          EV loss
          <em
            className={trainingTrendTone(trend.average_ev_loss_delta_bb, true)}
          >
            {formatEvLossDeltaBb(trend.average_ev_loss_delta_bb)}
          </em>
        </strong>
      ) : null}
    </small>
  );
}
