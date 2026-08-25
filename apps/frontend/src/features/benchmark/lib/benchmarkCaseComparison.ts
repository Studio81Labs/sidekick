import { humanReadableMessage } from "../../../shared/api/core";
import { benchmarkPercent } from "../../../shared/lib/metricPresentation";
import type {
  BenchmarkCaseResult,
  BenchmarkReport,
} from "../../../shared/types/benchmarks";
import { benchmarkFieldLabel } from "../../training/lib/trainingPresentation";
import { benchmarkReportsAreComparable } from "./benchmarkReportPresentation";

export type BenchmarkCaseTrend =
  | "regressed"
  | "recovered"
  | "mixed"
  | "unchanged";

export type BenchmarkCaseFilter =
  | "all"
  | Exclude<BenchmarkCaseTrend, "unchanged">;

export type BenchmarkCaseChangeTrend = Extract<
  BenchmarkCaseTrend,
  "regressed" | "recovered"
>;

export interface BenchmarkCaseChange {
  key: string;
  label: string;
  trend: BenchmarkCaseChangeTrend;
  previousValue: unknown;
  currentValue: unknown;
}

export function benchmarkCaseTrend(
  benchmarkCase: BenchmarkCaseResult,
  previousCase: BenchmarkCaseResult,
): BenchmarkCaseTrend {
  if (benchmarkCase.status !== previousCase.status) {
    return benchmarkCase.status === "error" ? "regressed" : "recovered";
  }
  if (benchmarkCase.accuracy < previousCase.accuracy) {
    return "regressed";
  }
  if (benchmarkCase.accuracy > previousCase.accuracy) {
    return "recovered";
  }
  const previousComparisons = new Map(
    previousCase.comparisons.map((comparison) => [
      comparison.field,
      comparison,
    ]),
  );
  let regressed = false;
  let recovered = false;
  for (const comparison of benchmarkCase.comparisons) {
    const previousComparison = previousComparisons.get(comparison.field);
    if (
      !previousComparison ||
      comparison.matched === previousComparison.matched
    ) {
      continue;
    }
    if (comparison.matched) {
      recovered = true;
    } else {
      regressed = true;
    }
  }
  if (regressed && recovered) {
    return "mixed";
  }
  if (regressed) {
    return "regressed";
  }
  if (recovered) {
    return "recovered";
  }
  return "unchanged";
}

export function benchmarkCaseStatusValue(
  benchmarkCase: BenchmarkCaseResult,
): string {
  if (benchmarkCase.status === "error") {
    return humanReadableMessage(benchmarkCase.error, "Parser failed");
  }
  return `Completed at ${benchmarkPercent(benchmarkCase.accuracy)}`;
}

export function benchmarkCaseChanges(
  benchmarkCase: BenchmarkCaseResult,
  previousCase: BenchmarkCaseResult,
): BenchmarkCaseChange[] {
  if (benchmarkCase.status !== previousCase.status) {
    return [
      {
        key: "parser-status",
        label: "Parser status",
        trend: benchmarkCase.status === "error" ? "regressed" : "recovered",
        previousValue: benchmarkCaseStatusValue(previousCase),
        currentValue: benchmarkCaseStatusValue(benchmarkCase),
      },
    ];
  }
  const previousComparisons = new Map(
    previousCase.comparisons.map((comparison) => [
      comparison.field,
      comparison,
    ]),
  );
  const currentFields = new Set<string>();
  const changes: BenchmarkCaseChange[] = [];
  for (const comparison of benchmarkCase.comparisons) {
    currentFields.add(comparison.field);
    const previousComparison = previousComparisons.get(comparison.field);
    if (previousComparison?.matched === comparison.matched) {
      continue;
    }
    changes.push({
      key: comparison.field,
      label: benchmarkFieldLabel(comparison.field),
      trend: comparison.matched ? "recovered" : "regressed",
      previousValue: previousComparison
        ? previousComparison.detected
        : "Not evaluated",
      currentValue: comparison.detected,
    });
  }
  for (const previousComparison of previousCase.comparisons) {
    if (currentFields.has(previousComparison.field)) {
      continue;
    }
    changes.push({
      key: previousComparison.field,
      label: benchmarkFieldLabel(previousComparison.field),
      trend: "regressed",
      previousValue: previousComparison.detected,
      currentValue: "Not evaluated",
    });
  }
  return changes;
}

export function benchmarkCaseTrendMap(
  report: BenchmarkReport | null,
  previousReport: BenchmarkReport | null,
): Map<string, BenchmarkCaseTrend> {
  const trends = new Map<string, BenchmarkCaseTrend>();
  if (
    !report ||
    !previousReport ||
    !benchmarkReportsAreComparable(report, previousReport)
  ) {
    return trends;
  }
  const previousCases = new Map(
    previousReport.cases.map((benchmarkCase) => [
      benchmarkCase.job_id,
      benchmarkCase,
    ]),
  );
  for (const benchmarkCase of report.cases) {
    const previousCase = previousCases.get(benchmarkCase.job_id);
    if (previousCase) {
      trends.set(
        benchmarkCase.job_id,
        benchmarkCaseTrend(benchmarkCase, previousCase),
      );
    }
  }
  return trends;
}
