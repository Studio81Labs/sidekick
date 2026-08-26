import { Eye } from "lucide-react";

import "./TrainingSolverCoverage.css";
import { ButtonControl } from "../../../shared/components/FormControls";
import {
  accessiblePointDelta,
  benchmarkPercent,
  formatAccuracyDelta,
  formatEvLossBb,
  formatEvLossDeltaBb,
  trainingTrendTone,
  trainingTrendWindowLabel,
} from "../../../shared/lib/metricPresentation";
import { SectionHeading } from "../../../shared/components/SectionHeading";
import type { Street } from "../../../shared/types/poker";
import type {
  TrainingSolverCoverage as TrainingSolverCoverageModel,
  TrainingSolverFilter,
  TrainingTrend,
} from "../../../shared/types/training";

const TRAINING_STREET_ORDER: readonly Street[] = [
  "preflop",
  "flop",
  "turn",
  "river",
];

type SolverPerformanceSummary = {
  action_accuracy?: number;
  exact_accuracy?: number;
  ev_compared_hands?: number;
  average_ev_loss_bb?: number | null;
  trend?: TrainingTrend | null;
};

export interface TrainingSolverCoverageProps {
  controlsDisabled: boolean;
  coverage: TrainingSolverCoverageModel | null | undefined;
  engineLabel: (engine: string) => string;
  onFilterChange: (filter: TrainingSolverFilter) => void | Promise<void>;
}

function solverPerformanceAccessibleLabel(
  summary: SolverPerformanceSummary,
): string | null {
  if (
    typeof summary.action_accuracy !== "number" ||
    typeof summary.exact_accuracy !== "number"
  ) {
    return null;
  }
  const evLoss =
    (summary.ev_compared_hands ?? 0) > 0 &&
    typeof summary.average_ev_loss_bb === "number"
      ? `average EV loss ${formatEvLossBb(summary.average_ev_loss_bb)}`
      : "EV loss ungraded";
  const labels = [
    `Action accuracy ${benchmarkPercent(summary.action_accuracy)}`,
    `exact-line accuracy ${benchmarkPercent(summary.exact_accuracy)}`,
    evLoss,
  ];
  if (summary.trend) {
    const changes = [
      `action accuracy change ${accessiblePointDelta(summary.trend.action_accuracy_delta)}`,
      `exact-line accuracy change ${accessiblePointDelta(summary.trend.exact_accuracy_delta)}`,
    ];
    if (summary.trend.average_ev_loss_delta_bb !== null) {
      changes.push(
        `average EV loss change ${formatEvLossDeltaBb(summary.trend.average_ev_loss_delta_bb)}`,
      );
    }
    labels.push(
      `${trainingTrendWindowLabel(summary.trend)}: ${changes.join(", ")}`,
    );
  }
  return labels.join("; ");
}

function SolverPerformance({ summary }: { summary: SolverPerformanceSummary }) {
  if (
    typeof summary.action_accuracy !== "number" ||
    typeof summary.exact_accuracy !== "number"
  ) {
    return null;
  }
  const trendTitle = summary.trend
    ? trainingTrendWindowLabel(summary.trend)
    : undefined;
  const evLoss =
    (summary.ev_compared_hands ?? 0) > 0 &&
    typeof summary.average_ev_loss_bb === "number"
      ? `${formatEvLossBb(summary.average_ev_loss_bb)} EV loss`
      : "EV ungraded";
  return (
    <small className="training-solver-performance" aria-hidden="true">
      <span>
        Action {benchmarkPercent(summary.action_accuracy)}
        {summary.trend ? (
          <em
            className={trainingTrendTone(summary.trend.action_accuracy_delta)}
            title={trendTitle}
          >
            {formatAccuracyDelta(summary.trend.action_accuracy_delta)}
          </em>
        ) : null}
      </span>
      <span>
        Exact {benchmarkPercent(summary.exact_accuracy)}
        {summary.trend ? (
          <em
            className={trainingTrendTone(summary.trend.exact_accuracy_delta)}
            title={trendTitle}
          >
            {formatAccuracyDelta(summary.trend.exact_accuracy_delta)}
          </em>
        ) : null}
      </span>
      <span>
        {evLoss}
        {summary.trend?.average_ev_loss_delta_bb !== null &&
        summary.trend?.average_ev_loss_delta_bb !== undefined ? (
          <em
            className={trainingTrendTone(
              summary.trend.average_ev_loss_delta_bb,
              true,
            )}
            title={trendTitle}
          >
            {formatEvLossDeltaBb(summary.trend.average_ev_loss_delta_bb)}
          </em>
        ) : null}
      </span>
    </small>
  );
}

function solverStreetCountsLabel(
  counts: Partial<Record<Street, number>>,
): string {
  return TRAINING_STREET_ORDER.filter((street) => (counts[street] ?? 0) > 0)
    .map((street) => `${street.charAt(0).toUpperCase()} ${counts[street]}`)
    .join(" · ");
}

export function TrainingSolverCoverage({
  controlsDisabled,
  coverage,
  engineLabel,
  onFilterChange,
}: TrainingSolverCoverageProps) {
  if (!coverage || coverage.total_hands <= 0) {
    return null;
  }

  return (
    <section
      className="training-progress-section training-solver-section"
      aria-labelledby="training-solver-title"
    >
      <SectionHeading
        className="training-section-heading"
        heading="Solver coverage"
        headingId="training-solver-title"
      >
        <span className="training-section-context">
          {coverage.tracked_hands} attributed
          {" · "}
          {coverage.unattributed_hands > 0 ? (
            <ButtonControl
              variant="ghost"
              className="training-solver-unattributed"
              onClick={() =>
                void onFilterChange({
                  kind: "unattributed",
                  label: "Unattributed recommendations",
                })
              }
              disabled={controlsDisabled}
              aria-label={`Show ${coverage.unattributed_hands} unattributed ${coverage.unattributed_hands === 1 ? "hand" : "hands"}`}
              title="Show training hands"
            >
              {coverage.unattributed_hands} unattributed
              <Eye size={11} aria-hidden="true" />
            </ButtonControl>
          ) : (
            <>0 unattributed</>
          )}
          {" · "}
          {coverage.fallback_hands} fallback
          {" ("}
          {benchmarkPercent(coverage.fallback_rate)})
        </span>
      </SectionHeading>
      {coverage.trend ? (
        <div
          className="training-solver-trend"
          aria-label="Solver coverage trend"
        >
          <span>
            Last {coverage.trend.window_hands}
            {" vs previous "}
            {coverage.trend.window_hands}
          </span>
          <div>
            <small>Attribution</small>
            <strong>
              {benchmarkPercent(coverage.trend.recent_attribution_rate)}
            </strong>
            <em
              className={trainingTrendTone(
                coverage.trend.attribution_rate_delta,
              )}
            >
              {formatAccuracyDelta(coverage.trend.attribution_rate_delta)}
            </em>
          </div>
          <div>
            <small>Fallback</small>
            <strong>
              {benchmarkPercent(coverage.trend.recent_fallback_rate)}
            </strong>
            <em
              className={trainingTrendTone(
                coverage.trend.fallback_rate_delta,
                true,
              )}
            >
              {formatAccuracyDelta(coverage.trend.fallback_rate_delta)}
            </em>
          </div>
        </div>
      ) : null}
      {coverage.routes.length > 0 ? (
        <table className="training-street-table training-solver-table">
          <thead>
            <tr>
              <th>Engine</th>
              <th>Hands</th>
              <th>Share</th>
              <th>Streets</th>
              <th>Fallback</th>
            </tr>
          </thead>
          <tbody>
            {coverage.routes.map((route) => {
              const label = engineLabel(route.engine);
              return (
                <tr key={route.key}>
                  <th scope="row">
                    <ButtonControl
                      variant="ghost"
                      className="training-solver-route"
                      onClick={() =>
                        void onFilterChange({
                          kind: "route",
                          key: route.key,
                          label,
                        })
                      }
                      disabled={controlsDisabled}
                      aria-label={[
                        `Show ${route.hands} ${route.hands === 1 ? "hand" : "hands"} handled by ${label}`,
                        solverPerformanceAccessibleLabel(route),
                      ]
                        .filter(Boolean)
                        .join(". ")}
                      title="Show training hands"
                    >
                      <span className="training-solver-route-name">
                        {label}
                      </span>
                      <Eye size={12} aria-hidden="true" />
                      <SolverPerformance summary={route} />
                    </ButtonControl>
                  </th>
                  <td>{route.hands}</td>
                  <td>
                    {benchmarkPercent(
                      route.hands / Math.max(coverage.tracked_hands, 1),
                    )}
                  </td>
                  <td className="training-solver-streets">
                    {solverStreetCountsLabel(route.street_counts) || "—"}
                  </td>
                  <td>{route.fallback_hands || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      {coverage.fallback_reasons.length > 0 ? (
        <div className="training-solver-fallbacks">
          <h4>Fallback reasons</h4>
          {coverage.fallback_reasons.map((fallback) => (
            <ButtonControl
              key={fallback.key}
              variant="ghost"
              className="training-solver-fallback"
              onClick={() =>
                void onFilterChange({
                  kind: "fallback",
                  key: fallback.key,
                  label: fallback.reason,
                })
              }
              disabled={controlsDisabled}
              aria-label={[
                `Show ${fallback.hands} ${fallback.hands === 1 ? "hand" : "hands"} using fallback: ${fallback.reason}`,
                solverPerformanceAccessibleLabel(fallback),
              ]
                .filter(Boolean)
                .join(". ")}
              title="Show training hands"
            >
              <span>{fallback.reason}</span>
              <em>{solverStreetCountsLabel(fallback.street_counts) || "—"}</em>
              <SolverPerformance summary={fallback} />
              <strong>{fallback.hands}</strong>
              <Eye size={13} aria-hidden="true" />
            </ButtonControl>
          ))}
        </div>
      ) : null}
    </section>
  );
}
